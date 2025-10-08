"""Helper widgets giving sections a lightweight framed appearance."""

from __future__ import annotations

from dataclasses import dataclass

import wx

_HIGHLIGHT_BLEND_LIGHT = 0.72
_HIGHLIGHT_BLEND_DARK = 0.45
_SHADOW_BLEND_LIGHT = 0.18
_SHADOW_BLEND_DARK = 0.36
_EDGE_BLEND_LIGHT = 0.28
_EDGE_BLEND_DARK = 0.52


class SectionContainer(wx.Panel):
    """Panel drawing a subtle outline to separate grouped content."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        background: wx.Colour | None = None,
    ) -> None:
        super().__init__(parent, style=wx.BORDER_NONE)
        self._chrome: _SectionChrome | None = None
        self.SetDoubleBuffered(True)
        self.SetBackgroundStyle(wx.BG_STYLE_PAINT)
        resolved = background if background and background.IsOk() else _resolve_background(self)
        super().SetBackgroundColour(resolved)
        self._chrome = _SectionChrome(self)

    def SetBackgroundColour(self, colour: wx.Colour | wx.ColourBase) -> bool:  # type: ignore[override]
        """Ensure chrome colours follow the panel background."""
        changed = super().SetBackgroundColour(colour)
        if changed and self._chrome:
            self._chrome.refresh_palette()
        return changed


@dataclass
class _SectionPalette:
    background: wx.Colour
    highlight: wx.Colour
    shadow: wx.Colour
    edge: wx.Colour


class _SectionChrome:
    """State holder drawing separators for a :class:`SectionContainer`."""

    def __init__(self, panel: SectionContainer) -> None:
        self.panel = panel
        self.palette = _build_palette(panel)
        self._bind_events()

    def refresh_palette(self) -> None:
        self.palette = _build_palette(self.panel)
        self.panel.Refresh()

    def _bind_events(self) -> None:
        self.panel.Bind(wx.EVT_PAINT, self._on_paint)
        self.panel.Bind(wx.EVT_SIZE, self._on_size)
        self.panel.Bind(wx.EVT_SHOW, self._on_show)
        self.panel.Bind(wx.EVT_SYS_COLOUR_CHANGED, self._on_sys_colour_changed)
        self.panel.Bind(wx.EVT_ERASE_BACKGROUND, self._suppress_background)

    def _on_paint(self, event: wx.Event) -> None:
        size = self.panel.GetClientSize()
        if size.width <= 0 or size.height <= 0:
            return
        dc = wx.AutoBufferedPaintDC(self.panel)
        palette = self.palette
        dc.SetPen(wx.TRANSPARENT_PEN)
        dc.SetBrush(wx.Brush(palette.background))
        dc.DrawRectangle(0, 0, size.width, size.height)
        width = size.width
        height = size.height
        if height > 0:
            dc.SetPen(wx.Pen(palette.highlight))
            dc.DrawLine(0, 0, width, 0)
            if height > 1:
                dc.SetPen(wx.Pen(palette.shadow))
                dc.DrawLine(0, height - 1, width, height - 1)
        if height > 2:
            dc.SetPen(wx.Pen(palette.edge))
            dc.DrawLine(0, 0, 0, height - 1)
            if width > 1:
                dc.DrawLine(width - 1, 0, width - 1, height - 1)

    def _on_size(self, event: wx.Event) -> None:
        event.Skip()
        self.panel.Refresh()

    def _on_show(self, event: wx.ShowEvent) -> None:
        event.Skip()
        if event.IsShown():
            self.panel.Refresh()

    def _on_sys_colour_changed(self, event: wx.SysColourChangedEvent) -> None:
        event.Skip()
        self.refresh_palette()

    def _suppress_background(self, event: wx.EraseEvent) -> None:
        # Fully handled in ``EVT_PAINT`` to avoid flicker.
        pass


def _build_palette(panel: SectionContainer) -> _SectionPalette:
    background = _resolve_background(panel)
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_3DHILIGHT)
    shadow = wx.SystemSettings.GetColour(wx.SYS_COLOUR_3DSHADOW)
    dark_shadow = wx.SystemSettings.GetColour(wx.SYS_COLOUR_3DDKSHADOW)
    if not highlight.IsOk():
        highlight = wx.Colour(255, 255, 255)
    if not shadow.IsOk():
        shadow = wx.Colour(128, 128, 128)
    if not dark_shadow.IsOk():
        dark_shadow = shadow
    is_dark = _is_dark_colour(background)
    highlight_mix = _HIGHLIGHT_BLEND_DARK if is_dark else _HIGHLIGHT_BLEND_LIGHT
    shadow_mix = _SHADOW_BLEND_LIGHT if is_dark else _SHADOW_BLEND_DARK
    edge_mix = _EDGE_BLEND_LIGHT if is_dark else _EDGE_BLEND_DARK
    top_highlight = _blend(background, highlight, highlight_mix)
    bottom_shadow = _blend(background, dark_shadow if not is_dark else highlight, shadow_mix)
    edge_shadow = _blend(background, shadow if not is_dark else highlight, edge_mix)
    return _SectionPalette(
        background=background,
        highlight=top_highlight,
        shadow=bottom_shadow,
        edge=edge_shadow,
    )


def _resolve_background(window: wx.Window) -> wx.Colour:
    colour = window.GetBackgroundColour()
    if not colour.IsOk():
        parent = window.GetParent()
        if parent:
            parent_colour = parent.GetBackgroundColour()
            if parent_colour.IsOk():
                colour = parent_colour
    if not colour.IsOk():
        system_colour = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW)
        if system_colour.IsOk():
            colour = system_colour
    if not colour.IsOk():
        colour = wx.Colour(255, 255, 255)
    return wx.Colour(colour)


def _blend(base: wx.Colour, target: wx.Colour, factor: float) -> wx.Colour:
    factor = max(0.0, min(1.0, factor))
    return wx.Colour(
        int(round(base.Red() + (target.Red() - base.Red()) * factor)),
        int(round(base.Green() + (target.Green() - base.Green()) * factor)),
        int(round(base.Blue() + (target.Blue() - base.Blue()) * factor)),
    )


def _is_dark_colour(colour: wx.Colour) -> bool:
    luminance = (
        0.299 * colour.Red() + 0.587 * colour.Green() + 0.114 * colour.Blue()
    )
    return luminance < 128

