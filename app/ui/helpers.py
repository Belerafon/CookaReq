"""Common helper widgets and functions for UI components."""

from __future__ import annotations

from typing import Callable

import wx

from ..i18n import _


class HelpStaticBox(wx.StaticBoxSizer):
    """A ``wx.StaticBoxSizer`` with a built-in help button.

    The button is appended to the first row inside the static box so it sits on
    the same line as the first added control. This avoids manual coordinate
    calculations and relies on sizer layout for positioning.
    """

    def __init__(
        self,
        parent: wx.Window,
        label: str,
        help_text: str,
        on_help: Callable[[str], None],
        *,
        orient: int = wx.VERTICAL,
        border: int = 5,
    ) -> None:
        """Create static box sizer with help button."""
        box = wx.StaticBox(parent, label=label)
        super().__init__(box, orient)

        self._border = border
        self._btn = wx.Button(box, label="?", style=wx.BU_EXACTFIT)
        self._btn.Bind(wx.EVT_BUTTON, lambda _evt: on_help(help_text))
        self._has_header = False

    def _wrap_first(self, item: wx.Window | wx.Sizer, flag: int) -> wx.Sizer:
        """Wrap the first item with the help button row."""
        self._has_header = True
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(item, 1, flag & ~wx.ALL, 0)
        row.Add(self._btn, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, self._border)
        return row

    def Add(
        self,
        item: wx.Window | wx.Sizer,
        proportion: int = 0,
        flag: int = 0,
        border: int = 0,
        userData: object | None = None,
    ) -> wx.SizerItem:
        """Add an item to the sizer.

        The first added item is wrapped into a horizontal row alongside the
        help button. Subsequent items are forwarded to ``wx.StaticBoxSizer``
        unchanged.
        """
        if not self._has_header:
            row = self._wrap_first(item, flag)
            return super().Add(row, proportion, flag, border, userData)
        return super().Add(item, proportion, flag, border, userData)

    def Prepend(
        self,
        item: wx.Window | wx.Sizer,
        proportion: int = 0,
        flag: int = 0,
        border: int = 0,
        userData: object | None = None,
    ) -> wx.SizerItem:
        """Prepend an item, keeping the help button on the first row."""
        if not self._has_header:
            row = self._wrap_first(item, flag)
            return super().Prepend(row, proportion, flag, border, userData)
        return super().Insert(1, item, proportion, flag, border, userData)

    def Insert(
        self,
        index: int,
        item: wx.Window | wx.Sizer,
        proportion: int = 0,
        flag: int = 0,
        border: int = 0,
        userData: object | None = None,
    ) -> wx.SizerItem:
        """Insert an item at the given position.

        Indexing is performed as if the help row did not exist, so callers can
        treat this sizer like a regular ``StaticBoxSizer``.
        """
        if not self._has_header:
            row = self._wrap_first(item, flag)
            return super().Insert(index, row, proportion, flag, border, userData)
        return super().Insert(index + 1, item, proportion, flag, border, userData)


def show_help(parent: wx.Window, message: str, *, title: str | None = None) -> None:
    """Display a modal dialog with ``message``.

    Parameters
    ----------
    parent:
        Parent window for the dialog.
    message:
        Help text to show.
    title:
        Optional dialog title; defaults to ``"Hint"``.
    """

    dlg = wx.Dialog(
        parent,
        title=title or _("Hint"),
        style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
    )
    text = wx.TextCtrl(dlg, value=message, style=wx.TE_MULTILINE | wx.TE_READONLY)
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(text, 1, wx.ALL | wx.EXPAND, 10)
    btns = dlg.CreateStdDialogButtonSizer(wx.OK)
    if btns:
        sizer.Add(btns, 0, wx.ALL | wx.ALIGN_CENTER, 5)
    dlg.SetSizerAndFit(sizer)
    dlg.ShowModal()
    dlg.Destroy()


def make_help_button(parent: wx.Window, message: str) -> wx.Button:
    """Return a small question-mark button displaying ``message`` when clicked."""

    btn = wx.Button(parent, label="?", style=wx.BU_EXACTFIT)
    btn.Bind(wx.EVT_BUTTON, lambda _evt: show_help(parent, message))
    return btn


def format_error_message(error: object, *, fallback: str | None = None) -> str:
    """Normalize ``error`` objects for display in the UI.

    ``error`` may be a mapping with ``code``/``type`` and ``message`` fields,
    an exception instance or any other value.  Dictionaries are rendered as
    ``"code: message"`` pairs when possible.  If all attempts fail, returns the
    provided ``fallback`` or a localized "Unknown error" string.
    """

    if isinstance(error, dict):
        code = error.get("code") or error.get("type")
        message = error.get("message")
        parts = [str(part) for part in (code, message) if part]
        if parts:
            return ": ".join(parts)
    if isinstance(error, BaseException):
        text = str(error)
        if text:
            return text
    elif error:
        text = str(error)
        if text:
            return text
    if fallback is not None:
        return fallback
    return _("Unknown error")
