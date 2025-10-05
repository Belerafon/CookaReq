"""DataViewListCtrl with marquee selection support."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from contextlib import suppress
import logging

import wx
import wx.dataview as dv


logger = logging.getLogger(__name__)


class _NormalizedMouseEvent:
    """Proxy event that exposes coordinates in the list control space."""

    __slots__ = ("_event", "_owner")

    def __init__(self, event: wx.MouseEvent, owner: "MarqueeDataViewListCtrl") -> None:
        self._event = event
        self._owner = owner

    def GetPosition(self) -> wx.Point:
        return self._owner._translate_event_position(self._event)

    def Skip(self, *args, **kwargs) -> None:
        self._event.Skip(*args, **kwargs)

    def __getattr__(self, name: str):  # pragma: no cover - thin proxy
        return getattr(self._event, name)


class MarqueeDataViewListCtrl(dv.DataViewListCtrl):
    """Extend :class:`~wx.dataview.DataViewListCtrl` with marquee selection."""

    _MARQUEE_THRESHOLD = 3

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._marquee_origin: wx.Point | None = None
        self._marquee_active = False
        self._marquee_overlay: wx.Overlay | None = None
        self._overlay_target: wx.Window = self
        self._marquee_base: set[int] = set()
        self._marquee_additive = False
        self._after_left_down: list[Callable[[wx.MouseEvent], None]] = []
        self._after_left_up: list[Callable[[wx.MouseEvent], None]] = []
        self._marquee_begin: list[Callable[[wx.MouseEvent | None], None]] = []
        self._marquee_end: list[Callable[[wx.MouseEvent | None], None]] = []
        self._mouse_sources: tuple[wx.Window, ...] = ()
        self._install_mouse_bindings()

    # ------------------------------------------------------------------
    def bind_after_left_down(self, handler: Callable[[wx.MouseEvent], None]) -> None:
        """Register ``handler`` executed after marquee pre-processing."""

        if handler in self._after_left_down:
            return
        self._after_left_down.append(handler)

    # ------------------------------------------------------------------
    def bind_after_left_up(self, handler: Callable[[wx.MouseEvent], None]) -> None:
        """Register ``handler`` executed after marquee cleanup."""

        if handler in self._after_left_up:
            return
        self._after_left_up.append(handler)

    # ------------------------------------------------------------------
    def bind_on_marquee_begin(
        self, handler: Callable[[wx.MouseEvent | None], None]
    ) -> None:
        """Register ``handler`` invoked when marquee drag starts."""

        if handler in self._marquee_begin:
            return
        self._marquee_begin.append(handler)

    # ------------------------------------------------------------------
    def bind_on_marquee_end(
        self, handler: Callable[[wx.MouseEvent | None], None]
    ) -> None:
        """Register ``handler`` invoked when marquee drag finishes."""

        if handler in self._marquee_end:
            return
        self._marquee_end.append(handler)

    # ------------------------------------------------------------------
    def _translate_event_position(self, event: wx.MouseEvent) -> wx.Point:
        source = event.GetEventObject()
        if source is self or not isinstance(source, wx.Window):
            return event.GetPosition()
        screen = source.ClientToScreen(event.GetPosition())
        return self.ScreenToClient(screen)

    # ------------------------------------------------------------------
    def _wrap_mouse_event(self, event: wx.MouseEvent) -> _NormalizedMouseEvent:
        return _NormalizedMouseEvent(event, self)

    # ------------------------------------------------------------------
    def _mark_event_handled(self, event: wx.MouseEvent) -> bool:
        if getattr(event, "_marquee_handled", False):
            return False
        setattr(event, "_marquee_handled", True)
        return True

    # ------------------------------------------------------------------
    def _dispatch_handlers(
        self, handlers: Iterable[Callable[[wx.MouseEvent], None]], event: wx.MouseEvent
    ) -> None:
        proxy = self._wrap_mouse_event(event)
        for handler in tuple(handlers):
            try:
                handler(proxy)
            except Exception:  # pragma: no cover - defensive guard
                logger.exception("Marquee mouse handler failed")

    # ------------------------------------------------------------------
    def _dispatch_optional_handlers(
        self,
        handlers: Iterable[Callable[[wx.MouseEvent | None], None]],
        event: wx.MouseEvent | None,
    ) -> None:
        proxy = self._wrap_mouse_event(event) if event is not None else None
        for handler in tuple(handlers):
            try:
                handler(proxy)
            except Exception:  # pragma: no cover - defensive guard
                logger.exception("Marquee mouse handler failed")

    # ------------------------------------------------------------------
    def _install_mouse_bindings(self) -> None:
        sources: list[wx.Window] = [self]
        get_main_window = getattr(self, "GetMainWindow", None)
        if callable(get_main_window):
            with suppress(Exception):
                main_window = get_main_window()
            if isinstance(main_window, wx.Window) and main_window is not self:
                sources.append(main_window)
                self._overlay_target = main_window
        self._mouse_sources = tuple(sources)
        for source in self._mouse_sources:
            source.Bind(wx.EVT_LEFT_DOWN, self._on_left_down)
            source.Bind(wx.EVT_LEFT_UP, self._on_left_up)
            source.Bind(wx.EVT_MOTION, self._on_mouse_move)
            source.Bind(wx.EVT_LEAVE_WINDOW, self._on_mouse_leave)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_focus_lost)

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
        target = self._overlay_target
        if not target:
            target = self
        dc = wx.ClientDC(target)
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
        target = self._overlay_target
        if not target:
            target = self
        draw_rect = rect
        if target is not self:
            top_left_screen = self.ClientToScreen(rect.GetTopLeft())
            # ``GetBottomRight`` returns an inclusive point; add (1, 1) to keep width/height
            bottom_right = rect.GetBottomRight()
            bottom_right_screen = self.ClientToScreen(
                wx.Point(bottom_right.x + 1, bottom_right.y + 1)
            )
            top_left = target.ScreenToClient(top_left_screen)
            bottom_right = target.ScreenToClient(bottom_right_screen)
            draw_rect = wx.Rect(
                top_left.x,
                top_left.y,
                max(bottom_right.x - top_left.x, 1),
                max(bottom_right.y - top_left.y, 1),
            )
        dc = wx.ClientDC(target)
        overlay_dc = wx.DCOverlay(self._marquee_overlay, dc)
        overlay_dc.Clear()
        pen = wx.Pen(wx.Colour(0, 120, 215), 1)
        brush = wx.Brush(wx.Colour(0, 120, 215, 40))
        dc.SetPen(pen)
        dc.SetBrush(brush)
        dc.DrawRectangle(draw_rect)
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
                success, rect = item_rect
                if not success:
                    continue
                item_rect = rect
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
    def _start_marquee(self, event: wx.MouseEvent | None) -> None:
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
        self._dispatch_optional_handlers(self._marquee_begin, event)

    # ------------------------------------------------------------------
    def _finish_marquee(self, event: wx.MouseEvent | None = None) -> None:
        self._clear_overlay()
        self._marquee_origin = None
        self._marquee_base.clear()
        self._marquee_active = False
        if self.HasCapture():  # pragma: no cover - defensive
            with suppress(Exception):
                self.ReleaseMouse()
        self._dispatch_optional_handlers(self._marquee_end, event)

    # ------------------------------------------------------------------
    def _on_left_down(self, event: wx.MouseEvent) -> None:
        if not self._mark_event_handled(event):
            event.Skip()
            return
        self._marquee_origin = self._translate_event_position(event)
        self._marquee_base = self._selected_rows()
        modifiers = event.ControlDown() or event.CmdDown() or event.ShiftDown()
        self._marquee_additive = bool(modifiers)
        self._marquee_active = False
        self._clear_overlay()
        self._dispatch_handlers(self._after_left_down, event)
        event.Skip()

    # ------------------------------------------------------------------
    def _on_left_up(self, event: wx.MouseEvent) -> None:
        if not self._mark_event_handled(event):
            event.Skip()
            return
        if self._marquee_origin and self._marquee_active:
            self._update_marquee_selection(self._translate_event_position(event))
            self._finish_marquee(event)
        else:
            self._marquee_origin = None
            self._marquee_base.clear()
            self._marquee_active = False
            self._clear_overlay()
        self._dispatch_handlers(self._after_left_up, event)
        event.Skip()
        return

    # ------------------------------------------------------------------
    def _on_mouse_move(self, event: wx.MouseEvent) -> None:
        if not self._mark_event_handled(event):
            event.Skip()
            return
        if not self._marquee_origin or not event.LeftIsDown():
            event.Skip()
            return
        if not self._marquee_active:
            origin = self._marquee_origin
            pos = self._translate_event_position(event)
            if (
                abs(pos.x - origin.x) <= self._MARQUEE_THRESHOLD
                and abs(pos.y - origin.y) <= self._MARQUEE_THRESHOLD
            ):
                event.Skip()
                return
            self._start_marquee(event)
        self._update_marquee_selection(self._translate_event_position(event))
        event.Skip(False)

    # ------------------------------------------------------------------
    def _on_mouse_leave(self, event: wx.MouseEvent) -> None:
        if not self._mark_event_handled(event):
            event.Skip()
            return
        if self._marquee_origin and not event.LeftIsDown():
            self._finish_marquee(event)
        event.Skip()

    # ------------------------------------------------------------------
    def _on_focus_lost(self, event: wx.FocusEvent) -> None:
        if self._marquee_origin:
            self._finish_marquee(None)
        event.Skip()


__all__ = ["MarqueeDataViewListCtrl"]

