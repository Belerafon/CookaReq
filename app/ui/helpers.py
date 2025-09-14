"""Common helper widgets and functions for UI components."""
from __future__ import annotations

from typing import Callable

import wx


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
        box = wx.StaticBox(parent, label=label)
        super().__init__(box, orient)

        self._border = border
        self._btn = wx.Button(box, label="?", style=wx.BU_EXACTFIT)
        self._btn.Bind(wx.EVT_BUTTON, lambda _evt: on_help(help_text))
        self._has_header = False

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
            self._has_header = True
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(item, 1, flag & ~wx.ALL, 0)
            row.Add(self._btn, 0, wx.LEFT | wx.ALIGN_CENTER_VERTICAL, self._border)
            return super().Add(row, proportion, flag, border, userData)
        return super().Add(item, proportion, flag, border, userData)
