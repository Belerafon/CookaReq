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
        self._overlay_target: wx.Window | None = None
        self._marquee_origin: wx.Point | None = None
        self._marquee_active = False
        self._marquee_overlay: wx.Overlay | None = None
        self._marquee_base: set[int] = set()
        self._marquee_additive = False
        self._capture_window: wx.Window | None = None

        self.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
        self.Bind(wx.EVT_LEFT_UP, self._on_left_up)
        self.Bind(wx.EVT_MOTION, self._on_mouse_move)
        self.Bind(wx.EVT_LEAVE_WINDOW, self._on_mouse_leave)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_mouse_leave)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)

    # ------------------------------------------------------------------
    def is_marquee_active(self) -> bool:
        """Return ``True`` while the drag-selection rectangle is visible."""

        return self._marquee_active

    # ------------------------------------------------------------------
    def _overlay_window(self) -> wx.Window:
        target = self._overlay_target
        if isinstance(target, wx.Window):
            try:
                if target and not target.IsBeingDeleted():
                    return target
            except RuntimeError:  # pragma: no cover - defensive guard
                pass
        candidate = self.GetMainWindow()
        if isinstance(candidate, wx.Window):
            target = candidate
        else:
            target = self
        self._overlay_target = target
        return target

    # ------------------------------------------------------------------
    @staticmethod
    def _as_point(value: wx.Point | tuple[int, int]) -> wx.Point:
        if isinstance(value, wx.Point):
            return wx.Point(value)
        return wx.Point(*value)

    # ------------------------------------------------------------------
    def _translate_point(
        self, point: wx.Point, *, source: wx.Window, target: wx.Window
    ) -> wx.Point:
        if source is target:
            return wx.Point(point)
        try:
            screen = source.ClientToScreen(point)
            mapped = target.ScreenToClient(screen)
        except Exception:  # pragma: no cover - defensive guard
            return wx.Point(point)
        return wx.Point(mapped)

    # ------------------------------------------------------------------
    def _event_position(self, event: wx.MouseEvent) -> wx.Point:
        point = self._as_point(event.GetPosition())
        source = event.GetEventObject()
        if isinstance(source, wx.Window) and source is not self:
            point = self._translate_point(point, source=source, target=self)
        return self._translate_point(point, source=self, target=self._overlay_window())

    # ------------------------------------------------------------------
    def _rect_to_overlay(self, rect: wx.Rect) -> wx.Rect:
        target = self._overlay_window()
        if target is self:
            return wx.Rect(rect)
        top_left = wx.Point(rect.x, rect.y)
        bottom_right = wx.Point(rect.x + rect.width, rect.y + rect.height)
        mapped_top_left = self._translate_point(top_left, source=self, target=target)
        mapped_bottom_right = self._translate_point(
            bottom_right, source=self, target=target
        )
        width = max(mapped_bottom_right.x - mapped_top_left.x, 1)
        height = max(mapped_bottom_right.y - mapped_top_left.y, 1)
        return wx.Rect(mapped_top_left.x, mapped_top_left.y, width, height)

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
        overlay = self._marquee_overlay
        if not overlay:
            return
        target = self._overlay_window()
        if not isinstance(target, wx.Window):
            return
        dc = wx.ClientDC(target)
        overlay_dc = wx.DCOverlay(overlay, dc)
        overlay_dc.Clear()
        del overlay_dc
        overlay.Reset()
        self._marquee_overlay = None

    # ------------------------------------------------------------------
    def _draw_overlay(self, rect: wx.Rect) -> None:
        if not hasattr(wx, "Overlay") or not hasattr(wx, "DCOverlay"):
            return
        target = self._overlay_window()
        if not isinstance(target, wx.Window):
            return
        if self._marquee_overlay is None:
            self._marquee_overlay = wx.Overlay()
        dc = wx.ClientDC(target)
        overlay_dc = wx.DCOverlay(self._marquee_overlay, dc)
        overlay_dc.Clear()
        pen = wx.Pen(wx.Colour(0, 120, 215), 1)
        brush = wx.Brush(wx.Colour(0, 120, 215, 40))
        dc.SetPen(pen)
        dc.SetBrush(brush)
        dc.DrawRectangle(rect)
        del overlay_dc

    # ------------------------------------------------------------------
    def _item_rect(self, item: dv.DataViewItem) -> wx.Rect | None:
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
        return self._rect_to_overlay(rect)

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
        self._draw_overlay(rect)
        selected: set[int] = set()
        count = self.GetItemCount()
        for row in range(count):
            item = self.RowToItem(row)
            if not item or not item.IsOk():
                continue
            item_rect = self._item_rect(item)
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
        if self.HasCapture():
            self._capture_window = self
            return
        try:
            self.CaptureMouse()
        except Exception:  # pragma: no cover - defensive guard
            return
        if self.HasCapture():
            self._capture_window = self

    # ------------------------------------------------------------------
    def _finish_marquee(self) -> None:
        self._clear_overlay()
        self._marquee_origin = None
        self._marquee_base.clear()
        self._marquee_active = False
        self._marquee_additive = False
        capture_window = self._capture_window
        self._capture_window = None
        if isinstance(capture_window, wx.Window) and capture_window.HasCapture():
            with suppress(Exception):
                capture_window.ReleaseMouse()

    # ------------------------------------------------------------------
    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self._marquee_origin = self._event_position(event)
        self._marquee_base = self._selected_rows()
        modifiers = event.ControlDown() or event.CmdDown() or event.ShiftDown()
        self._marquee_additive = bool(modifiers)
        self._marquee_active = False
        self._clear_overlay()
        event.Skip()

    # ------------------------------------------------------------------
    def _on_left_up(self, event: wx.MouseEvent) -> None:
        if self._marquee_origin and self._marquee_active:
            self._update_marquee_selection(self._event_position(event))
            self._finish_marquee()
            return
        self._marquee_origin = None
        self._marquee_base.clear()
        self._marquee_active = False
        self._marquee_additive = False
        self._clear_overlay()
        event.Skip()

    # ------------------------------------------------------------------
    def _on_mouse_move(self, event: wx.MouseEvent) -> None:
        if not self._marquee_origin or not event.LeftIsDown():
            event.Skip()
            return
        if not self._marquee_active:
            origin = self._marquee_origin
            pos = self._event_position(event)
            if (
                abs(pos.x - origin.x) <= self._MARQUEE_THRESHOLD
                and abs(pos.y - origin.y) <= self._MARQUEE_THRESHOLD
            ):
                event.Skip()
                return
            self._start_marquee()
        self._update_marquee_selection(self._event_position(event))
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

