from __future__ import annotations

from collections.abc import Callable

import pytest

from app.ui.agent_chat_panel.history_view import HistoryInteractionPreparation, HistoryView


class _DummyItem:
    def __init__(self, row: int) -> None:
        self.row = row

    def IsOk(self) -> bool:
        return True


class _DummyListCtrl:
    def __init__(self, *, hit_row: int | None = 0, item_count: int = 1) -> None:
        self._hit_row = hit_row
        self._item_count = item_count
        self.bound: list[tuple[object, Callable[..., None]]] = []
        self.selected: list[int] = []
        self.unselect_calls = 0
        self.focus_calls = 0
        self.ensure_visible_rows: list[int] = []

    def Bind(self, event: object, handler: Callable[..., None]) -> None:
        self.bound.append((event, handler))

    def HitTest(self, _pos: object) -> tuple[_DummyItem | None, int]:
        if self._hit_row is None:
            return None, -1
        return _DummyItem(self._hit_row), 0

    def UnselectAll(self) -> None:
        self.unselect_calls += 1

    def SetFocus(self) -> None:
        self.focus_calls += 1

    def ItemToRow(self, item: _DummyItem) -> int:
        return item.row

    def RowToItem(self, row: int) -> _DummyItem:
        return _DummyItem(row)

    def SelectRow(self, row: int) -> None:
        self.selected.append(row)

    def EnsureVisible(self, item: _DummyItem) -> None:
        self.ensure_visible_rows.append(item.row)

    def GetItemCount(self) -> int:
        return self._item_count


class _DummyMarqueeListCtrl(_DummyListCtrl):
    def __init__(self, *, hit_row: int | None = 0, item_count: int = 1) -> None:
        super().__init__(hit_row=hit_row, item_count=item_count)
        self.after_left_down: list[Callable[[object], None]] = []
        self.after_left_up: list[Callable[[object], None]] = []
        self.marquee_begin: list[Callable[[object | None], None]] = []
        self.marquee_end: list[Callable[[object | None], None]] = []

    def bind_after_left_down(self, handler: Callable[[object], None]) -> None:
        self.after_left_down.append(handler)

    def bind_after_left_up(self, handler: Callable[[object], None]) -> None:
        self.after_left_up.append(handler)

    def bind_on_marquee_begin(self, handler: Callable[[object | None], None]) -> None:
        self.marquee_begin.append(handler)

    def bind_on_marquee_end(self, handler: Callable[[object | None], None]) -> None:
        self.marquee_end.append(handler)

    def fire_after_left_down(self) -> _DummyMouseEvent:
        event = _DummyMouseEvent()
        for handler in list(self.after_left_down):
            handler(event)
        return event

    def fire_after_left_up(self) -> _DummyMouseEvent:
        event = _DummyMouseEvent()
        for handler in list(self.after_left_up):
            handler(event)
        return event

    def fire_marquee_begin(self) -> None:
        for handler in list(self.marquee_begin):
            handler(None)

    def fire_marquee_end(self) -> None:
        for handler in list(self.marquee_end):
            handler(None)


class _DummyMouseEvent:
    def __init__(self) -> None:
        self.skipped = False

    def GetPosition(self) -> tuple[int, int]:
        return (0, 0)

    def Skip(self, _flag: bool = True) -> None:
        self.skipped = True


class _HistoryViewFactory:
    def __init__(self) -> None:
        self._conversations: list[object] = [object()]

    def create(
        self,
        *,
        list_ctrl: _DummyListCtrl,
        is_running: Callable[[], bool] | None = None,
        prepare_interaction: Callable[[], bool] | None = None,
    ) -> HistoryView:
        return HistoryView(
            list_ctrl,
            get_conversations=lambda: self._conversations,
            format_row=lambda _conversation: ("demo",),
            get_active_index=lambda: 0,
            activate_conversation=lambda _index: None,
            handle_delete_request=lambda _rows: None,
            is_running=is_running or (lambda: False),
            splitter=object(),
            prepare_interaction=prepare_interaction,
        )


@pytest.mark.unit
def test_prepare_for_interaction_default_allows_interaction() -> None:
    list_ctrl = _DummyListCtrl()
    view = _HistoryViewFactory().create(list_ctrl=list_ctrl)

    preparation = view._prepare_for_interaction()

    assert preparation == HistoryInteractionPreparation(True, False)


@pytest.mark.unit
def test_prepare_for_interaction_invokes_callback() -> None:
    list_ctrl = _DummyListCtrl()
    calls: list[bool] = []

    def prepare() -> bool:
        calls.append(True)
        return True

    view = _HistoryViewFactory().create(
        list_ctrl=list_ctrl,
        prepare_interaction=prepare,
    )

    preparation = view._prepare_for_interaction()

    assert calls == [True]
    assert preparation == HistoryInteractionPreparation(True, True)


@pytest.mark.unit
def test_prepare_for_interaction_blocks_when_running() -> None:
    list_ctrl = _DummyListCtrl()
    view = _HistoryViewFactory().create(
        list_ctrl=list_ctrl,
        is_running=lambda: True,
    )

    preparation = view._prepare_for_interaction()

    assert preparation == HistoryInteractionPreparation(False, False)


@pytest.mark.unit
def test_prepare_for_interaction_handles_callback_failure() -> None:
    list_ctrl = _DummyListCtrl()

    def prepare() -> bool:
        raise RuntimeError("boom")

    view = _HistoryViewFactory().create(
        list_ctrl=list_ctrl,
        prepare_interaction=prepare,
    )

    preparation = view._prepare_for_interaction()

    assert preparation == HistoryInteractionPreparation(False, False)


@pytest.mark.unit
def test_mouse_down_selects_row_without_prepare_callback() -> None:
    selected_indices: list[int] = []

    def activate(index: int) -> None:
        selected_indices.append(index)

    list_ctrl = _DummyListCtrl(hit_row=0)
    factory = _HistoryViewFactory()
    view = HistoryView(
        list_ctrl,
        get_conversations=lambda: factory._conversations,
        format_row=lambda _conversation: ("demo",),
        get_active_index=lambda: 0,
        activate_conversation=activate,
        handle_delete_request=lambda _rows: None,
        is_running=lambda: False,
        splitter=object(),
        prepare_interaction=None,
    )

    event = _DummyMouseEvent()
    view._on_mouse_down(event)

    assert selected_indices == []
    assert list_ctrl.selected == []
    assert list_ctrl.ensure_visible_rows == []
    assert event.skipped

    up_event = _DummyMouseEvent()
    view._on_mouse_up(up_event)

    assert selected_indices == [0]
    assert list_ctrl.ensure_visible_rows == [0]
    assert up_event.skipped


@pytest.mark.unit
def test_mouse_down_aborts_when_not_allowed() -> None:
    list_ctrl = _DummyListCtrl(hit_row=0)
    factory = _HistoryViewFactory()
    view = HistoryView(
        list_ctrl,
        get_conversations=lambda: factory._conversations,
        format_row=lambda _conversation: ("demo",),
        get_active_index=lambda: 0,
        activate_conversation=lambda _index: None,
        handle_delete_request=lambda _rows: None,
        is_running=lambda: True,
        splitter=object(),
        prepare_interaction=None,
    )

    event = _DummyMouseEvent()
    view._on_mouse_down(event)

    assert list_ctrl.selected == []
    assert event.skipped

    up_event = _DummyMouseEvent()
    view._on_mouse_up(up_event)

    assert list_ctrl.selected == []
    assert up_event.skipped
 

@pytest.mark.unit
def test_mouse_down_uses_marquee_hook_when_available() -> None:
    selected_indices: list[int] = []

    def activate(index: int) -> None:
        selected_indices.append(index)

    list_ctrl = _DummyMarqueeListCtrl(hit_row=0)
    factory = _HistoryViewFactory()
    HistoryView(
        list_ctrl,
        get_conversations=lambda: factory._conversations,
        format_row=lambda _conversation: ("demo",),
        get_active_index=lambda: 0,
        activate_conversation=activate,
        handle_delete_request=lambda _rows: None,
        is_running=lambda: False,
        splitter=object(),
        prepare_interaction=None,
    )

    assert len(list_ctrl.after_left_down) == 1
    assert len(list_ctrl.after_left_up) == 1
    assert len(list_ctrl.marquee_begin) == 1
    assert len(list_ctrl.marquee_end) == 1

    down_event = list_ctrl.fire_after_left_down()

    assert selected_indices == []
    assert down_event.skipped

    up_event = list_ctrl.fire_after_left_up()

    assert selected_indices == [0]
    assert up_event.skipped


@pytest.mark.unit
def test_marquee_drag_suppresses_activation() -> None:
    selected_indices: list[int] = []

    def activate(index: int) -> None:
        selected_indices.append(index)

    list_ctrl = _DummyMarqueeListCtrl(hit_row=0)
    factory = _HistoryViewFactory()
    view = HistoryView(
        list_ctrl,
        get_conversations=lambda: factory._conversations,
        format_row=lambda _conversation: ("demo",),
        get_active_index=lambda: 0,
        activate_conversation=activate,
        handle_delete_request=lambda _rows: None,
        is_running=lambda: False,
        splitter=object(),
        prepare_interaction=None,
    )

    list_ctrl.fire_after_left_down()
    list_ctrl.fire_marquee_begin()
    list_ctrl.fire_marquee_end()
    list_ctrl.fire_after_left_up()

    assert selected_indices == []
