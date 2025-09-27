"""Shutdown routines shared by the main frame mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING

import wx

from ...log import logger

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


class MainFrameShutdownMixin:
    """Handle auxiliary windows and graceful shutdown."""

    _detached_editors: dict
    _shutdown_in_progress: bool

    def register_auxiliary_frame(self: MainFrame, frame: wx.Frame) -> None:
        """Ensure ``frame`` is configured to follow the main window lifecycle."""

        if frame is None:
            return
        def _ensure_destroy(event: wx.CloseEvent) -> None:  # pragma: no cover - GUI event
            event.Skip()
            if not frame.IsBeingDeleted():
                frame.Destroy()

        frame.Bind(wx.EVT_CLOSE, _ensure_destroy)
        extra_style = frame.GetExtraStyle()
        frame.SetExtraStyle(extra_style | wx.FRAME_FLOAT_ON_PARENT)

    def _request_exit_main_loop(self: MainFrame) -> None:
        """Ask wx to terminate the main loop if it is still running."""

        app = wx.GetApp()
        if not app:
            return

        exit_main_loop = getattr(app, "ExitMainLoop", None)
        if not callable(exit_main_loop):
            return

        is_running = getattr(app, "IsMainLoopRunning", None)
        try:
            if callable(is_running) and not is_running():
                return
        except Exception:  # pragma: no cover - defensive guard around wx API
            logger.exception("Failed to query wx main loop state before shutdown")

        try:
            exit_main_loop()
        except Exception:  # pragma: no cover - wx implementations may vary
            logger.exception("Failed to request wx main loop exit during shutdown")

    def _on_close(self: MainFrame, event: wx.Event) -> None:  # pragma: no cover - GUI event
        if self._shutdown_in_progress:
            if event is not None:
                event.Skip()
            return

        event_type = type(event).__name__ if event is not None else "<none>"
        logger.info("Main frame close requested (event=%s)", event_type)
        can_veto = bool(event and hasattr(event, "CanVeto") and event.CanVeto())
        if not self._confirm_discard_changes():
            if event is not None and hasattr(event, "Veto") and can_veto:
                event.Veto()
            return
        self._shutdown_in_progress = True
        try:
            self._save_layout()
        except Exception:  # pragma: no cover - best effort cleanup
            logger.exception("Failed to save main frame layout during shutdown")

        for frame in list(self._detached_editors.values()):
            if frame is None:
                continue
            frame.Destroy()
        self._detached_editors.clear()

        self._detach_log_handler()

        try:
            self.mcp.stop()
        except Exception:  # pragma: no cover - controller stop must not block close
            logger.exception("Failed to stop MCP controller during shutdown")

        self.DestroyChildren()

        if event is not None:
            event.Skip()

            def _finalize_close() -> None:
                if not self.IsBeingDeleted():
                    self.Destroy()
                self._request_exit_main_loop()

            wx.CallAfter(_finalize_close)
        else:
            if not self.IsBeingDeleted():
                self.Destroy()
            self._request_exit_main_loop()
