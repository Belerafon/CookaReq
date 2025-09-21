"""Shutdown routines shared by the main frame mixins."""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING

import wx

from ...log import logger

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


class MainFrameShutdownMixin:
    """Handle auxiliary windows and graceful shutdown."""

    _detached_editors: dict
    _auxiliary_frames: set[wx.Frame]
    _shutdown_in_progress: bool

    def register_auxiliary_frame(self: "MainFrame", frame: wx.Frame) -> None:
        """Track ``frame`` so it is destroyed during main window shutdown."""

        if frame is None:
            return
        if frame in self._auxiliary_frames:
            return

        owner_ref = weakref.ref(self)
        frame_ref = weakref.ref(frame)

        def _on_aux_close(event: wx.Event) -> None:  # pragma: no cover - GUI event
            owner = owner_ref()
            target = frame_ref()
            if owner is not None and target is not None:
                owner._auxiliary_frames.discard(target)
            event.Skip()

        frame.Bind(wx.EVT_CLOSE, _on_aux_close)
        self._auxiliary_frames.add(frame)

    def _close_auxiliary_frames(self: "MainFrame") -> None:
        """Destroy all registered auxiliary frames, ignoring errors."""

        remaining = len(self._auxiliary_frames)
        logger.info(
            "Shutdown step: closing %s auxiliary window(s)",
            remaining,
        )
        for aux in list(self._auxiliary_frames):
            if aux is None:
                continue
            try:
                if aux.IsBeingDeleted():
                    continue
                try:
                    if aux.IsShownOnScreen():
                        aux.Show(False)
                except Exception:  # pragma: no cover - defensive guard
                    logger.exception("Failed to hide auxiliary window during shutdown")
                closed = False
                try:
                    close = getattr(aux, "Close", None)
                    if callable(close):
                        try:
                            closed = bool(close(force=True))
                        except TypeError:
                            closed = bool(close(True))
                except Exception:  # pragma: no cover - close handlers must not abort shutdown
                    logger.exception("Failed to close auxiliary window during shutdown")
                if not closed and not aux.IsBeingDeleted():
                    aux.Destroy()
            except Exception:  # pragma: no cover - best effort cleanup
                logger.exception("Failed to destroy auxiliary window during shutdown")
        self._auxiliary_frames.clear()
        logger.info("Shutdown step completed: auxiliary windows closed")

    def _request_exit_main_loop(self: "MainFrame") -> None:
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

    def _on_close(self: "MainFrame", event: wx.Event) -> None:  # pragma: no cover - GUI event
        if self._shutdown_in_progress:
            if event is not None:
                event.Skip()
            return

        event_type = type(event).__name__ if event is not None else "<none>"
        can_veto = False
        if event is not None and hasattr(event, "CanVeto"):
            try:  # pragma: no cover - defensive guard around wx API
                can_veto = bool(event.CanVeto())
            except Exception:  # pragma: no cover - wx implementations may vary
                can_veto = False
        editor_dirty = bool(getattr(self, "editor", None) and self.editor.is_dirty())
        logger.info(
            "Close requested: event=%s, can_veto=%s, editor_dirty=%s",
            event_type,
            can_veto,
            editor_dirty,
        )
        if not self._confirm_discard_changes():
            logger.warning(
                "Close vetoed: pending edits remain and user declined to discard",
            )
            if event is not None and hasattr(event, "Veto") and can_veto:
                event.Veto()
            return
        self._shutdown_in_progress = True
        logger.info("Proceeding with shutdown sequence")
        logger.info("Shutdown step: saving layout")
        try:
            self._save_layout()
        except Exception:  # pragma: no cover - best effort cleanup
            logger.exception("Shutdown step failed: error while saving layout")
        else:
            logger.info("Shutdown step completed: layout persisted")

        remaining_editors = len(self._detached_editors)
        logger.info(
            "Shutdown step: closing %s detached editor window(s)",
            remaining_editors,
        )
        for frame in list(self._detached_editors.values()):
            try:
                frame.Destroy()
            except Exception:  # pragma: no cover - best effort cleanup
                logger.exception("Failed to destroy detached editor during shutdown")
        self._detached_editors.clear()
        logger.info("Shutdown step completed: detached editors closed")

        self._close_auxiliary_frames()

        logger.info("Shutdown step: detaching wx log handler")
        try:
            self._detach_log_handler()
        except Exception:  # pragma: no cover - best effort cleanup
            logger.exception("Failed to detach log handler during shutdown")

        mcp_running = False
        try:
            mcp_running = self.mcp.is_running()
        except Exception:  # pragma: no cover - defensive guard around controller
            logger.exception("Failed to query MCP controller state before shutdown")
        logger.info("Shutdown step: stopping MCP controller (running=%s)", mcp_running)
        try:
            self.mcp.stop()
        except Exception:  # pragma: no cover - controller stop must not block close
            logger.exception("Shutdown step failed: MCP controller stop raised an error")
        else:
            logger.info("Shutdown step completed: MCP controller stopped")

        if event is not None:
            event.Skip()
            logger.info("Shutdown sequence handed off to wx for finalization")

            def _finalize_close() -> None:
                if not self.IsBeingDeleted():
                    self.Destroy()
                self._request_exit_main_loop()

            wx.CallAfter(_finalize_close)
        else:
            logger.info("Shutdown sequence completed without wx event object")
            if not self.IsBeingDeleted():
                self.Destroy()
            self._request_exit_main_loop()
