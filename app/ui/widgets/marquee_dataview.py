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
        self._marquee_base: set[int] = set()
        self._marquee_additive = False

        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOTION, self._on_mouse_move)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_mouse_leave)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_mouse_leave)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)

    # ------------------------------------------------------------------
    @staticmethod
    def _as_point(value: wx.Point | tuple[int, int]) -> wx.Point:
        if isinstance(value, wx.Point):
            return wx.Point(value)
        return wx.Point(*value)

    # ------------------------------------------------------------------
    def _normalize_event_position(self, event: wx.MouseEvent) -> wx.Point:
        point = self._as_point(event.GetPosition())
        source = event.GetEventObject()
        if isinstance(source, wx.Window) and source is not self:
            try:
                screen = source.ClientToScreen(point)
                point = self.ScreenToClient(screen)
            except Exception:  # pragma: no cover - defensive guard
                return wx.Point(point)
        return wx.Point(point)

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
    def _item_rect(self, row: int) -> wx.Rect | None:
        item = self.RowToItem(row)
        if not item or not item.IsOk():
            return None
        try:
            result = self.GetItemRect(item)
        except Exception:  # pragma: no cover - defensive guard
            return None
        if isinstance(result, tuple):
            success, rect = result
            if not success:
                return None
        else:
            rect = result
        if not isinstance(rect, wx.Rect):  # pragma: no cover - defensive
            return None
        return wx.Rect(rect)

    # ------------------------------------------------------------------
    def _update_marquee_selection(self, current: wx.Point) -> None:
        origin = self._marquee_origin
        if origin is None:
            return
        left = min(origin.x, current.x)
        top = min(origin.y, current.y)
        right = max(origin.x, current.x)
        bottom = max(origin.y, current.y)
        rect = wx.Rect(left, top, max(right - left, 1), max(bottom - top, 1))
        selected: set[int] = set()
        count = self.GetItemCount()
        for row in range(count):
            item_rect = self._item_rect(row)
            if item_rect is None:
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
        self._marquee_origin = None
        self._marquee_base.clear()
        self._marquee_active = False
        self._marquee_additive = False
        if self.HasCapture():  # pragma: no cover - defensive
            with suppress(Exception):
                self.ReleaseMouse()

    # ------------------------------------------------------------------
    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self._marquee_origin = self._normalize_event_position(event)
        self._marquee_base = self._selected_rows()
        modifiers = event.ControlDown() or event.CmdDown() or event.ShiftDown()
        self._marquee_additive = bool(modifiers)
        self._marquee_active = False
        event.Skip()

    # ------------------------------------------------------------------
    def _on_left_up(self, event: wx.MouseEvent) -> None:
        if self._marquee_origin and self._marquee_active:
            self._update_marquee_selection(self._normalize_event_position(event))
            self._finish_marquee()
            return
        self._marquee_origin = None
        self._marquee_base.clear()
        self._marquee_active = False
        self._marquee_additive = False
        event.Skip()

    # ------------------------------------------------------------------
    def _on_mouse_move(self, event: wx.MouseEvent) -> None:
        if not self._marquee_origin or not event.LeftIsDown():
            event.Skip()
            return
        if not self._marquee_active:
            origin = self._marquee_origin
            pos = self._normalize_event_position(event)
            if (
                abs(pos.x - origin.x) <= self._MARQUEE_THRESHOLD
                and abs(pos.y - origin.y) <= self._MARQUEE_THRESHOLD
            ):
                event.Skip()
                return
            self._start_marquee()
        self._update_marquee_selection(self._normalize_event_position(event))
        event.Skip(False)

    # ------------------------------------------------------------------
    def _on_mouse_leave(self, event: wx.MouseEvent) -> None:
        if self._marquee_origin and not event.LeftIsDown():
            self._finish_marquee()
        event.Skip()

    # ------------------------------------------------------------------
    def _on_capture_lost(self, event: wx.MouseCaptureLostEvent) -> None:
        self._finish_marquee()
        event.Skip()


__all__ = ["MarqueeDataViewListCtrl"]

