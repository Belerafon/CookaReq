from collections.abc import Callable

import pytest

from app.ui.agent_chat_panel.history_view import (
    HistoryInteractionPreparation,
    HistoryView,
)


class _DummyItem:
    def __init__(self, row: int | None) -> None:
        self.row = row

    def IsOk(self) -> bool:
        return self.row is not None


class _DummyListCtrl:
    def __init__(self, *, hit_row: int | None = 0, item_count: int = 1) -> None:
        self._hit_row = hit_row
        self._item_count = item_count
        self.bound: list[tuple[object, Callable[..., None]]] = []
        self.selected: list[int] = []
        self.unselect_calls = 0
        self.focus_calls = 0
        self.ensure_visible_rows: list[int] = []
        self.appended_rows: list[tuple[str, ...]] = []
        self.freeze_calls = 0
        self.thaw_calls = 0

    def Bind(self, event: object, handler: Callable[..., None]) -> None:
        self.bound.append((event, handler))

    def HitTest(self, _pos: object) -> tuple[_DummyItem | None, int]:
        if self._hit_row is None:
            return None, -1
        return _DummyItem(self._hit_row), 0

    def UnselectAll(self) -> None:
        self.unselect_calls += 1
        self.selected.clear()

    def SetFocus(self) -> None:
        self.focus_calls += 1

    def ItemToRow(self, item: _DummyItem) -> int:
        assert item.row is not None
        return item.row

    def RowToItem(self, row: int) -> _DummyItem:
        return _DummyItem(row)

    def SelectRow(self, row: int) -> None:
        if row not in self.selected:
            self.selected.append(row)

    def Select(self, item: _DummyItem) -> None:
        if item.row is not None:
            self.SelectRow(item.row)

    def UnselectRow(self, row: int) -> None:
        if row in self.selected:
            self.selected.remove(row)

    def IsRowSelected(self, row: int) -> bool:
        return row in self.selected

    def EnsureVisible(self, item: _DummyItem) -> None:
        if item.row is not None:
            self.ensure_visible_rows.append(item.row)

    def GetItemCount(self) -> int:
        return self._item_count

    def GetSelections(self) -> list[_DummyItem]:
        return [_DummyItem(row) for row in self.selected]

    def GetSelection(self) -> _DummyItem | None:
        if not self.selected:
            return None
        return _DummyItem(self.selected[-1])

    def DeleteAllItems(self) -> None:
        self.selected.clear()

    def AppendItem(self, row: tuple[str, ...]) -> None:
        self.appended_rows.append(row)

    def Freeze(self) -> None:
        self.freeze_calls += 1

    def Thaw(self) -> None:
        self.thaw_calls += 1


class _DummyMouseEvent:
    def __init__(self) -> None:
        self.skipped = False

    def GetPosition(self) -> tuple[int, int]:
        return (0, 0)

    def Skip(self, _flag: bool = True) -> None:
        self.skipped = True


class _DummyDataViewEvent:
    def __init__(self, row: int | None) -> None:
        self._row = row
        self.skipped = False

    def GetItem(self) -> _DummyItem | None:
        if self._row is None:
            return None
        return _DummyItem(self._row)

    def Skip(self, _flag: bool = True) -> None:
        self.skipped = True


class _HistoryViewFactory:
    def __init__(self) -> None:
        self._conversations: list[object] = [object()]

    def create(
        self,
        *,
        list_ctrl: _DummyListCtrl,
        activate: Callable[[int], None] | None = None,
        is_running: Callable[[], bool] | None = None,
        prepare_interaction: Callable[[], bool] | None = None,
    ) -> HistoryView:
        return HistoryView(
            list_ctrl,
            get_conversations=lambda: self._conversations,
            format_row=lambda _conversation: ("demo",),
            get_active_index=lambda: 0,
            activate_conversation=activate or (lambda _index: None),
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
def test_mouse_down_clears_selection_on_background_click() -> None:
    list_ctrl = _DummyListCtrl(hit_row=None)
    view = _HistoryViewFactory().create(list_ctrl=list_ctrl)

    event = _DummyMouseEvent()
    view._on_mouse_down(event)

    assert list_ctrl.unselect_calls == 1
    assert list_ctrl.focus_calls == 1
    assert event.skipped


@pytest.mark.unit
def test_mouse_down_respects_blocking_state() -> None:
    list_ctrl = _DummyListCtrl(hit_row=0)
    view = _HistoryViewFactory().create(
        list_ctrl=list_ctrl,
        is_running=lambda: True,
    )

    event = _DummyMouseEvent()
    view._on_mouse_down(event)

    assert list_ctrl.unselect_calls == 0
    assert list_ctrl.focus_calls == 0
    assert event.skipped


@pytest.mark.unit
def test_selection_activation_when_allowed() -> None:
    selected_indices: list[int] = []

    def activate(index: int) -> None:
        selected_indices.append(index)

    list_ctrl = _DummyListCtrl(hit_row=0)
    factory = _HistoryViewFactory()
    view = factory.create(list_ctrl=list_ctrl, activate=activate)

    event = _DummyDataViewEvent(0)
    view._on_select_history(event)

    assert selected_indices == [0]
    assert event.skipped


@pytest.mark.unit
def test_selection_ignored_when_interaction_blocked() -> None:
    selected_indices: list[int] = []

    def activate(index: int) -> None:
        selected_indices.append(index)

    list_ctrl = _DummyListCtrl(hit_row=0)
    factory = _HistoryViewFactory()
    view = factory.create(
        list_ctrl=list_ctrl,
        activate=activate,
        is_running=lambda: True,
    )

    event = _DummyDataViewEvent(0)
    view._on_select_history(event)

    assert selected_indices == []
    assert event.skipped
