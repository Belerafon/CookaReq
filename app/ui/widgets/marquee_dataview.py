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
        self._drag_origin: wx.Point | None = None
        self._dragging = False
        self._initial_selection: set[int] = set()
        self._extend_selection = False

        self._marquee_sources = self._determine_event_sources()
        for window in self._marquee_sources:
            window.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
            window.Bind(wx.EVT_LEFT_UP, self._on_left_up)
            window.Bind(wx.EVT_MOTION, self._on_mouse_move)
            window.Bind(wx.EVT_LEAVE_WINDOW, self._on_mouse_leave)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_mouse_leave)
        self.Bind(wx.EVT_MOUSE_CAPTURE_LOST, self._on_capture_lost)

    # ------------------------------------------------------------------
    def _determine_event_sources(self) -> tuple[wx.Window, ...]:
        sources: list[wx.Window] = [self]
        get_main = getattr(self, "GetMainWindow", None)
        main_window: wx.Window | None = None
        if callable(get_main):
            with suppress(Exception):
                main_window = get_main()
            if isinstance(main_window, wx.Window) and main_window not in sources:
                sources.append(main_window)
        return tuple(sources)

    # ------------------------------------------------------------------
    def _normalize_event_position(self, event: wx.MouseEvent) -> wx.Point:
        point = wx.Point(event.GetPosition())
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
    def _current_selection(self) -> set[int]:
        rows: set[int] = set()
        for item in self.GetSelections():
            if not item or not item.IsOk():
                continue
            row = self.ItemToRow(item)
            if row != wx.NOT_FOUND:
                rows.add(row)
        return rows

    # ------------------------------------------------------------------
    def _update_marquee_selection(self, current: wx.Point) -> None:
        origin = self._drag_origin
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
        if self._extend_selection:
            selected.update(self._initial_selection)
        self._apply_selection(selected)

    # ------------------------------------------------------------------
    def _apply_selection(self, indices: set[int]) -> None:
        if indices == self._current_selection():
            return
        self.UnselectAll()
        for row in sorted(indices):
            with suppress(Exception):
                self.SelectRow(row)
        if indices:
            item = self.RowToItem(min(indices))
            if item and item.IsOk():
                with suppress(Exception):
                    self.SetCurrentItem(item)

    # ------------------------------------------------------------------
    def _start_marquee(self) -> None:
        self._dragging = True
        if not self._extend_selection:
            with suppress(Exception):
                self.UnselectAll()
        if not self.HasCapture():  # pragma: no cover - defensive
            with suppress(Exception):
                self.CaptureMouse()

    # ------------------------------------------------------------------
    def _finish_marquee(self) -> None:
        self._drag_origin = None
        self._initial_selection.clear()
        self._dragging = False
        self._extend_selection = False
        if self.HasCapture():  # pragma: no cover - defensive
            with suppress(Exception):
                self.ReleaseMouse()

    # ------------------------------------------------------------------
    def _on_left_down(self, event: wx.MouseEvent) -> None:
        self._drag_origin = self._normalize_event_position(event)
        self._initial_selection = self._selected_rows()
        modifiers = event.ControlDown() or event.CmdDown() or event.ShiftDown()
        self._extend_selection = bool(modifiers)
        self._dragging = False
        event.Skip()

    # ------------------------------------------------------------------
    def _on_left_up(self, event: wx.MouseEvent) -> None:
        if self._drag_origin and self._dragging:
            self._update_marquee_selection(self._normalize_event_position(event))
            self._finish_marquee()
            return
        self._drag_origin = None
        self._initial_selection.clear()
        self._dragging = False
        self._extend_selection = False
        event.Skip()

    # ------------------------------------------------------------------
    def _on_mouse_move(self, event: wx.MouseEvent) -> None:
        if not self._drag_origin or not event.LeftIsDown():
            event.Skip()
            return
        if not self._dragging:
            origin = self._drag_origin
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
        if self._drag_origin and not event.LeftIsDown():
            self._finish_marquee()
        event.Skip()

    # ------------------------------------------------------------------
    def _on_capture_lost(self, event: wx.MouseCaptureLostEvent) -> None:
        self._finish_marquee()
        event.Skip()


__all__ = ["MarqueeDataViewListCtrl"]

