"""DataViewListCtrl with marquee selection support."""

from __future__ import annotations

from contextlib import suppress

import wx
import wx.dataview as dv


class MarqueeDataViewListCtrl(dv.DataViewListCtrl):
    """Extend :class:`~wx.dataview.DataViewListCtrl` with marquee selection."""

    _MARQUEE_THRESHOLD = 3

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._marquee_origin: wx.Point | None = None
        self._marquee_active = False
        self._marquee_overlay: wx.Overlay | None = None
        self._marquee_base: set[int] = set()
        self._marquee_additive = False
        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOTION, self._on_mouse_move)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_mouse_leave)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_mouse_leave)

    # ------------------------------------------------------------------
    def _selected_rows(self) -> set[int]:
        selections = set()
        for item in self.GetSelections():
            if not item or not item.IsOk():
                continue
            row = self.ItemToRow(item)
            if row != wx.NOT_FOUND:
                selections.add(row)
        return selections

    # ------------------------------------------------------------------
    def _clear_overlay(self) -> None:
        if not self._marquee_overlay:
            return
        dc = wx.ClientDC(self)
        overlay_dc = wx.DCOverlay(self._marquee_overlay, dc)
        overlay_dc.Clear()
        del overlay_dc
        self._marquee_overlay.Reset()
        self._marquee_overlay = None

    # ------------------------------------------------------------------
    def _draw_overlay(self, rect: wx.Rect) -> None:
        if not hasattr(wx, "Overlay") or not hasattr(wx, "DCOverlay"):
            return
        if self._marquee_overlay is None:
            self._marquee_overlay = wx.Overlay()
        dc = wx.ClientDC(self)
        overlay_dc = wx.DCOverlay(self._marquee_overlay, dc)
        overlay_dc.Clear()
        pen = wx.Pen(wx.Colour(0, 120, 215), 1)
        brush = wx.Brush(wx.Colour(0, 120, 215, 40))
        dc.SetPen(pen)
        dc.SetBrush(brush)
        dc.DrawRectangle(rect)
        del overlay_dc

    # ------------------------------------------------------------------
    def _update_marquee_selection(self, current: wx.Point) -> None:
        if self._marquee_origin is None:
            return
        left = min(self._marquee_origin.x, current.x)
        top = min(self._marquee_origin.y, current.y)
        right = max(self._marquee_origin.x, current.x)
        bottom = max(self._marquee_origin.y, current.y)
        rect = wx.Rect(left, top, max(right - left, 1), max(bottom - top, 1))
        self._draw_overlay(rect)
        selected: set[int] = set()
        count = self.GetItemCount()
        for row in range(count):
            item = self.RowToItem(row)
            if not item or not item.IsOk():
                continue
            try:
                item_rect = self.GetItemRect(item)
            except Exception:
                continue
            if isinstance(item_rect, tuple):  # pragma: no cover - defensive
                item_rect = item_rect[0]
            if not isinstance(item_rect, wx.Rect):  # pragma: no cover - defensive
                continue
            if rect.Intersects(item_rect):
                selected.add(row)
        if self._marquee_additive:
            selected.update(self._marquee_base)
        self._apply_selection(selected)

    # ------------------------------------------------------------------
    def _apply_selection(self, indices: set[int]) -> None:
        count = self.GetItemCount()
        for row in range(count):
            should_select = row in indices
            is_selected = self.IsRowSelected(row)
            if should_select == is_selected:
                continue
            if should_select:
                self.SelectRow(row)
            else:
                self.UnselectRow(row)
        if indices:
            focus_row = min(indices)
            item = self.RowToItem(focus_row)
            if item and item.IsOk():
                with suppress(Exception):
                    self.SetCurrentItem(item)

    # ------------------------------------------------------------------
    def _start_marquee(self) -> None:
        self._marquee_active = True
        if not self._marquee_additive:
            for row in list(self._marquee_base):
                try:
                    self.UnselectRow(row)
                except Exception:  # pragma: no cover - defensive
                    continue
            self._marquee_base.clear()
        if not self.HasCapture():  # pragma: no cover - defensive
            with suppress(Exception):
                self.CaptureMouse()

    # ------------------------------------------------------------------
    def _finish_marquee(self) -> None:
        self._clear_overlay()
        self._marquee_origin = None
        self._marquee_base.clear()
        self._marquee_active = False
        if self.HasCapture():  # pragma: no cover - defensive
            with suppress(Exception):
                self.ReleaseMouse()

    # ------------------------------------------------------------------
    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self._marquee_origin = event.GetPosition()
        self._marquee_base = self._selected_rows()
        modifiers = event.ControlDown() or event.CmdDown() or event.ShiftDown()
        self._marquee_additive = bool(modifiers)
        self._marquee_active = False
        self._clear_overlay()
        event.Skip()

    # ------------------------------------------------------------------
    def _on_left_up(self, event: wx.MouseEvent) -> None:
        if self._marquee_origin and self._marquee_active:
            self._update_marquee_selection(event.GetPosition())
            self._finish_marquee()
            return
        self._marquee_origin = None
        self._marquee_base.clear()
        self._marquee_active = False
        self._clear_overlay()
        event.Skip()

    # ------------------------------------------------------------------
    def _on_mouse_move(self, event: wx.MouseEvent) -> None:
        if not self._marquee_origin or not event.LeftIsDown():
            event.Skip()
            return
        if not self._marquee_active:
            origin = self._marquee_origin
            pos = event.GetPosition()
            if (
                abs(pos.x - origin.x) <= self._MARQUEE_THRESHOLD
                and abs(pos.y - origin.y) <= self._MARQUEE_THRESHOLD
            ):
                event.Skip()
                return
            self._start_marquee()
        self._update_marquee_selection(event.GetPosition())
        event.Skip(False)

    # ------------------------------------------------------------------
    def _on_mouse_leave(self, event: wx.MouseEvent) -> None:
        if self._marquee_origin and not event.LeftIsDown():
            self._finish_marquee()
        event.Skip()


__all__ = ["MarqueeDataViewListCtrl"]

