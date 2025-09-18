"""Helpers ensuring splitter sashes are easy to discover and drag."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import wx


class SplitterEventBlocker:
    """Re-entrant guard that suppresses splitter change callbacks."""

    def __init__(self) -> None:
        self._depth = 0

    @contextmanager
    def pause(self) -> Iterator[None]:
        """Temporarily increment the guard depth while yielding control."""

        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1

    @property
    def active(self) -> bool:
        """Return ``True`` when callbacks should be ignored."""

        return self._depth > 0

_DEFAULT_SASH_THICKNESS_DIP = 6
_TINT_FACTOR = 0.25
_MIN_THICKNESS = 4


def style_splitter(
    splitter: wx.SplitterWindow,
    *,
    sash_colour: wx.Colour | None = None,
    thickness: int | None = None,
) -> None:
    """Highlight ``splitter`` so the draggable sash is easy to find."""

    if not splitter:
        return
    accent = _resolve_colour(splitter, sash_colour)
    resolved_thickness = _resolve_thickness(splitter, thickness)
    helper = getattr(splitter, "_cooka_splitter_highlight", None)
    if helper is None:
        helper = _SplitterHighlighter(splitter, accent, resolved_thickness)
        splitter._cooka_splitter_highlight = helper  # type: ignore[attr-defined]
    else:
        helper.update(accent=accent, thickness=resolved_thickness)
    helper.refresh()


def refresh_splitter_highlight(splitter: wx.SplitterWindow) -> None:
    """Force ``splitter`` to repaint its sash highlight if configured."""

    helper = getattr(splitter, "_cooka_splitter_highlight", None)
    if helper is not None:
        helper.refresh()


class _SplitterHighlighter:
    """State holder responsible for tinting a ``wx.SplitterWindow`` sash."""

    def __init__(self, splitter: wx.SplitterWindow, accent: wx.Colour, thickness: int) -> None:
        self.splitter = splitter
        self.accent = accent
        self.thickness = thickness
        self._pending_draw = False
        self._bind_events()
        self.splitter.SetDoubleBuffered(True)

    def update(self, *, accent: wx.Colour, thickness: int) -> None:
        self.accent = accent
        self.thickness = thickness

    def refresh(self) -> None:
        self._apply_thickness()
        self._schedule_draw()

    def _bind_events(self) -> None:
        self.splitter.Bind(wx.EVT_PAINT, self._on_paint)
        self.splitter.Bind(wx.EVT_SIZE, self._on_size)
        self.splitter.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGED, self._on_sash_move)
        self.splitter.Bind(wx.EVT_SPLITTER_SASH_POS_CHANGING, self._on_sash_move)
        self.splitter.Bind(wx.EVT_SHOW, self._on_show)

    def _apply_thickness(self) -> None:
        desired = max(self.thickness, _MIN_THICKNESS)
        current = int(getattr(self.splitter, "SashSize", 0) or 0)
        if current < desired:
            try:
                self.splitter.SashSize = desired
            except Exception:
                pass

    def _on_paint(self, event: wx.Event) -> None:
        event.Skip()
        self._schedule_draw()

    def _on_size(self, event: wx.Event) -> None:
        event.Skip()
        self._schedule_draw()

    def _on_show(self, event: wx.ShowEvent) -> None:
        event.Skip()
        if event.IsShown():
            self._schedule_draw()

    def _on_sash_move(self, event: wx.SplitterEvent) -> None:
        event.Skip()
        self._schedule_draw()

    def _schedule_draw(self) -> None:
        if self._pending_draw:
            return
        self._pending_draw = True
        wx.CallAfter(self._draw)

    def _draw(self) -> None:
        self._pending_draw = False
        splitter = self.splitter
        if not splitter or not splitter:  # pragma: no cover - defensive
            return
        if hasattr(splitter, "IsSashInvisible") and splitter.IsSashInvisible():
            return
        if not splitter.IsSplit():
            return
        size = splitter.GetClientSize()
        if size.width <= 0 or size.height <= 0:
            return
        sash_size = int(getattr(splitter, "SashSize", 0) or 0)
        if sash_size <= 0:
            sash_size = max(self.thickness, _MIN_THICKNESS)
        sash_pos = splitter.GetSashPosition()
        mode = splitter.GetSplitMode()
        if mode == wx.SPLIT_VERTICAL:
            rect = wx.Rect(sash_pos, 0, sash_size, size.height)
        else:
            rect = wx.Rect(0, sash_pos, size.width, sash_size)
        try:
            dc = wx.ClientDC(splitter)
            dc.SetPen(wx.TRANSPARENT_PEN)
            dc.SetBrush(wx.Brush(self.accent))
            dc.DrawRectangle(rect)
        except Exception:  # pragma: no cover - GUI drawing best effort
            pass


def _resolve_thickness(splitter: wx.Window, thickness: int | None) -> int:
    if thickness is not None and thickness > 0:
        return thickness
    try:
        return max(int(splitter.FromDIP(_DEFAULT_SASH_THICKNESS_DIP)), _MIN_THICKNESS)
    except Exception:
        return max(_DEFAULT_SASH_THICKNESS_DIP, _MIN_THICKNESS)


def _resolve_colour(splitter: wx.Window, colour: wx.Colour | None) -> wx.Colour:
    if colour is not None and colour.IsOk():
        return wx.Colour(colour)
    highlight = wx.SystemSettings.GetColour(wx.SYS_COLOUR_HIGHLIGHT)
    if not highlight.IsOk():
        highlight = wx.Colour(0, 120, 215)
    tinted = _tint_colour(highlight, _TINT_FACTOR)
    background = splitter.GetBackgroundColour()
    if background.IsOk() and _colours_similar(tinted, background):
        tinted = _tint_colour(highlight, _TINT_FACTOR / 2)
    return tinted


def _tint_colour(colour: wx.Colour, factor: float) -> wx.Colour:
    factor = max(0.0, min(1.0, factor))
    r = colour.Red()
    g = colour.Green()
    b = colour.Blue()
    return wx.Colour(
        min(255, int(r + (255 - r) * factor)),
        min(255, int(g + (255 - g) * factor)),
        min(255, int(b + (255 - b) * factor)),
    )


def _colours_similar(a: wx.Colour, b: wx.Colour) -> bool:
    threshold = 24
    return (
        abs(a.Red() - b.Red()) <= threshold
        and abs(a.Green() - b.Green()) <= threshold
        and abs(a.Blue() - b.Blue()) <= threshold
    )
