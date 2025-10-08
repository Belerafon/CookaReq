"""Reusable dialog for presenting detailed error messages."""

from __future__ import annotations


import wx

from ..i18n import _


class ErrorDialog(wx.Dialog):
    """Dialog showing a copyable error message."""

    def __init__(self, parent: wx.Window | None, message: str, *, title: str) -> None:
        """Initialise the dialog and populate it with controls."""
        super().__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP,
        )
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        self._text = wx.TextCtrl(
            self,
            value=message,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        self._text.SetMinSize((400, 200))
        main_sizer.Add(self._text, 1, wx.ALL | wx.EXPAND, 10)

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self._copy_btn = wx.Button(self, wx.ID_COPY)
        self._copy_btn.Bind(wx.EVT_BUTTON, self._on_copy)
        button_sizer.Add(self._copy_btn, 0, wx.RIGHT, 5)

        close_btn = wx.Button(self, wx.ID_CLOSE)
        close_btn.Bind(wx.EVT_BUTTON, self._on_close)
        button_sizer.AddStretchSpacer()
        button_sizer.Add(close_btn, 0)

        main_sizer.Add(button_sizer, 0, wx.ALL | wx.EXPAND, 10)

        self.SetSizer(main_sizer)
        self.Layout()
        main_sizer.Fit(self)
        self._copy_btn.SetDefault()
        self.SetEscapeId(close_btn.GetId())

    def _on_copy(self, event: wx.CommandEvent | None) -> None:
        """Copy error text to clipboard."""
        clipboard = wx.TheClipboard
        opened = False
        try:
            opened = clipboard.Open()
            if not opened:
                return
            data = wx.TextDataObject()
            data.SetText(self._text.GetValue())
            clipboard.SetData(data)
        finally:
            if opened:
                clipboard.Close()
        if event is not None:
            event.Skip(False)

    def _on_close(self, event: wx.CommandEvent | None) -> None:
        """Close dialog."""
        self.EndModal(wx.ID_OK)
        if event is not None:
            event.Skip(False)


def show_error_dialog(
    parent: wx.Window | None,
    message: str,
    *,
    title: str | None = None,
) -> None:
    """Display an :class:`ErrorDialog` with ``message``."""
    dlg = ErrorDialog(parent, message, title=title or _("Error"))
    try:
        dlg.ShowModal()
    finally:
        dlg.Destroy()
