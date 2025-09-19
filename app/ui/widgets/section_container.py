"""Lightweight container panel used to group controls with a title."""

from __future__ import annotations

import wx


class SectionContainer(wx.Panel):
    """Simple wrapper applying the requested background colour."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        background: wx.Colour | None = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        if background and background.IsOk():
            super().SetBackgroundColour(background)

    def SetBackgroundColour(self, colour: wx.Colour | wx.ColourBase) -> bool:  # type: ignore[override]
        """Defer to :class:`wx.Panel` implementation without extra painting."""

        return super().SetBackgroundColour(colour)

