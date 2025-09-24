"""Logging console helpers for the main frame."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import wx

from ...i18n import _
from ...log import get_log_directory, logger, open_log_directory
from ..helpers import create_copy_button

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .frame import MainFrame


class WxLogHandler(logging.Handler):
    """Forward log records to a ``wx.TextCtrl``."""

    def __init__(self, target: wx.TextCtrl, *, max_chars: int = 500_000) -> None:
        """Initialize handler redirecting log output to ``target``."""
        super().__init__()
        self._target = target
        self._max_chars = max_chars
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

    @property
    def target(self) -> wx.TextCtrl:
        """Current ``wx.TextCtrl`` receiving log output."""
        return self._target

    @target.setter
    def target(self, new_target: wx.TextCtrl) -> None:
        """Redirect log output to ``new_target``."""
        self._target = new_target

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - GUI side effect
        """Append formatted ``record`` text to the log console."""

        if not wx.GetApp():
            return
        msg = self.format(record)
        wx.CallAfter(self._append_message, msg)

    def _append_message(self, message: str) -> None:
        """Render ``message`` in the target control respecting the size limit."""

        target = self._target
        if not target or target.IsBeingDeleted():
            return
        target.AppendText(message + "\n")
        if self._max_chars and self._max_chars > 0:
            excess = target.GetLastPosition() - self._max_chars
            if excess > 0:
                target.Remove(0, excess)


class MainFrameLoggingMixin:
    """Provide logging console integration for the main frame."""

    log_panel: wx.Panel
    log_label: wx.StaticText
    log_level_label: wx.StaticText
    log_level_choice: wx.Choice
    open_logs_button: wx.Button
    copy_logs_button: wx.Window
    log_console: wx.TextCtrl
    log_handler: WxLogHandler
    _log_level_values: list[int]

    def _init_log_console(self: "MainFrame") -> None:
        """Create the log console panel and attach handler."""

        self.log_panel = wx.Panel(self.main_splitter)
        log_sizer = wx.BoxSizer(wx.VERTICAL)
        header = wx.BoxSizer(wx.HORIZONTAL)
        self.log_label = wx.StaticText(self.log_panel, label=_("Log Console"))
        header.Add(self.log_label, 1, wx.ALIGN_CENTER_VERTICAL)
        self.log_level_label = wx.StaticText(self.log_panel, label=_("Log Level"))
        header.Add(self.log_level_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        self._log_level_values = []
        self.log_level_choice = wx.Choice(self.log_panel, choices=[])
        header.Add(self.log_level_choice, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 2)
        self.open_logs_button = wx.Button(
            self.log_panel,
            label=_("Open Log Folder"),
            style=wx.BU_EXACTFIT,
        )
        self.open_logs_button.Bind(wx.EVT_BUTTON, self.on_open_logs)
        header.Add(self.open_logs_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        self.copy_logs_button = create_copy_button(
            self.log_panel,
            tooltip=_("Copy log output to clipboard"),
            fallback_label=_("Copy logs"),
            handler=self.on_copy_logs,
        )
        header.Add(self.copy_logs_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)
        log_sizer.Add(header, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 5)
        self.log_console = wx.TextCtrl(
            self.log_panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        log_sizer.Add(self.log_console, 1, wx.EXPAND | wx.ALL, 5)
        self.log_panel.SetSizer(log_sizer)

        existing = next(
            (h for h in logger.handlers if isinstance(h, WxLogHandler)),
            None,
        )
        saved_log_level = self.config.get_log_level()
        if existing:
            self.log_handler = existing
            self.log_handler.target = self.log_console
        else:
            self.log_handler = WxLogHandler(self.log_console)
            logger.addHandler(self.log_handler)
        self.log_handler.setLevel(saved_log_level)
        self._populate_log_level_choice(saved_log_level)
        self.log_level_choice.Bind(wx.EVT_CHOICE, self.on_change_log_level)

    # ------------------------------------------------------------------
    # log level handling
    def _log_level_options(self) -> list[tuple[str, int]]:
        """Return ordered pairs of localized labels and log levels."""

        return [
            (_("Debug"), logging.DEBUG),
            (_("Info"), logging.INFO),
            (_("Warning"), logging.WARNING),
            (_("Error"), logging.ERROR),
        ]

    def _populate_log_level_choice(self, selected_level: int | None = None) -> None:
        """Fill the level selector preserving the current ``selected_level``."""

        if not getattr(self, "log_level_choice", None):
            return

        target_level = selected_level if selected_level is not None else self.log_handler.level
        if target_level == logging.NOTSET:
            target_level = logging.INFO

        options = self._log_level_options()
        self.log_level_choice.Freeze()
        try:
            self.log_level_choice.Clear()
            self._log_level_values = []
            for label, level in options:
                self.log_level_choice.Append(label)
                self._log_level_values.append(level)
        finally:
            self.log_level_choice.Thaw()

        index = self._find_choice_index_for_level(target_level)
        if index >= 0:
            self.log_level_choice.SetSelection(index)

    def _find_choice_index_for_level(self, level: int) -> int:
        """Return the closest matching index for ``level`` in the selector."""

        if not self._log_level_values:
            return -1
        if level in self._log_level_values:
            return self._log_level_values.index(level)
        for idx, candidate in enumerate(self._log_level_values):
            if level <= candidate:
                return idx
        return len(self._log_level_values) - 1

    def on_change_log_level(self, event: wx.CommandEvent) -> None:
        """Adjust the wx log handler level according to user selection."""

        if not getattr(self, "log_handler", None):
            return
        selection = event.GetSelection()
        if selection < 0 or selection >= len(self._log_level_values):
            return
        level = self._log_level_values[selection]
        self.log_handler.setLevel(level)
        self.config.set_log_level(level)

    # ------------------------------------------------------------------
    # visibility & labelling helpers
    def on_toggle_log_console(self, _event: wx.CommandEvent) -> None:
        """Toggle visibility of log console panel."""

        if self.navigation.log_menu_item.IsChecked():
            sash = self.config.get_log_sash(self.GetClientSize().height - 150)
            self.log_panel.Show()
            self.main_splitter.SplitHorizontally(self.doc_splitter, self.log_panel, sash)
        else:
            if self.main_splitter.IsSplit():
                self.config.set_log_sash(self.main_splitter.GetSashPosition())
            self.main_splitter.Unsplit(self.log_panel)
            self.log_panel.Hide()
        self.config.set_log_shown(self.navigation.log_menu_item.IsChecked())

    def update_log_console_labels(self) -> None:
        """Refresh captions for logging controls according to locale."""

        if not getattr(self, "log_label", None):
            return
        self.log_label.SetLabel(_("Log Console"))
        self.log_level_label.SetLabel(_("Log Level"))
        self.open_logs_button.SetLabel(_("Open Log Folder"))
        copy_label = _("Copy logs")
        copy_tooltip = _("Copy log output to clipboard")
        if getattr(self, "copy_logs_button", None):
            self.copy_logs_button.SetToolTip(copy_tooltip)
            if not isinstance(self.copy_logs_button, wx.BitmapButton):
                self.copy_logs_button.SetLabel(copy_label)
        self._populate_log_level_choice(self.log_handler.level)

    # ------------------------------------------------------------------
    # clipboard interaction
    def on_copy_logs(self, event: wx.CommandEvent | None) -> None:
        """Copy current log console text to the clipboard."""

        console = getattr(self, "log_console", None)
        if console is None or console.IsBeingDeleted():
            return
        text = console.GetValue()
        if not text:
            return

        clipboard = wx.TheClipboard
        opened = False
        try:
            opened = clipboard.Open()
            if not opened:
                return
            clipboard.SetData(wx.TextDataObject(text))
        finally:
            if opened:
                clipboard.Close()
        if event is not None:
            event.Skip(False)

    # ------------------------------------------------------------------
    # file system interaction
    def on_open_logs(self, _event: wx.CommandEvent) -> None:
        """Show the log directory in the system file browser."""

        from ...telemetry import log_event

        directory = get_log_directory()
        success = open_log_directory()
        log_event(
            "OPEN_LOG_FOLDER",
            {"directory": str(directory), "success": success},
        )
        if not success:
            from . import show_error_dialog

            message = _("Could not open log folder:\n%s") % directory
            show_error_dialog(self, message, title=_("Error"))

    def _detach_log_handler(self) -> None:
        """Remove the custom wx handler from the global logger."""

        if getattr(self, "log_handler", None) and self.log_handler in logger.handlers:
            logger.removeHandler(self.log_handler)
