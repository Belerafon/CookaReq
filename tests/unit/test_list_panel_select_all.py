"""Tests for bulk selection behaviour in ``ListPanel``."""
from __future__ import annotations

from bisect import bisect_left

import pytest


class _BaseFakeList:
    """Common helpers for faking ``wx.ListCtrl`` selection logic."""

    def __init__(self, count: int, selected: list[int] | None = None) -> None:
        self._count = count
        self._selected: list[int] = []
        for idx in selected or []:
            self._insert_selection(idx)
        self.state_calls: list[int] = []
        self.freeze_calls = 0
        self.thaw_calls = 0
        self.freeze_active = False
        self.focus_calls: list[int] = []
        self.ensure_calls: list[int] = []
        self.set_focus_calls = 0

    # ------------------------------------------------------------------
    def _insert_selection(self, index: int) -> None:
        if not (0 <= index < self._count):
            return
        pos = bisect_left(self._selected, index)
        if pos >= len(self._selected) or self._selected[pos] != index:
            self._selected.insert(pos, index)

    # ------------------------------------------------------------------
    def _remove_selection(self, index: int) -> None:
        pos = bisect_left(self._selected, index)
        if pos < len(self._selected) and self._selected[pos] == index:
            del self._selected[pos]

    # ------------------------------------------------------------------
    def GetItemCount(self) -> int:
        return self._count

    # ------------------------------------------------------------------
    def GetFirstSelected(self) -> int:
        return self._selected[0] if self._selected else -1

    # ------------------------------------------------------------------
    def GetNextSelected(self, index: int) -> int:
        pos = bisect_left(self._selected, index)
        if pos < len(self._selected) and self._selected[pos] == index:
            pos += 1
        return self._selected[pos] if pos < len(self._selected) else -1

    # ------------------------------------------------------------------
    def SetItemState(self, index: int, state: int, mask: int) -> None:
        if not self.freeze_active:
            raise AssertionError("Freeze() should be active during bulk selection")
        if state:
            self._insert_selection(index)
        else:
            self._remove_selection(index)
        self.state_calls.append(index)

    # ------------------------------------------------------------------
    def Freeze(self) -> None:
        self.freeze_calls += 1
        self.freeze_active = True

    # ------------------------------------------------------------------
    def Thaw(self) -> None:
        self.thaw_calls += 1
        self.freeze_active = False

    # ------------------------------------------------------------------
    def Focus(self, index: int) -> None:
        if self.freeze_active:
            raise AssertionError("Thaw() must run before Focus()")
        self.focus_calls.append(index)

    # ------------------------------------------------------------------
    def EnsureVisible(self, index: int) -> None:
        if self.freeze_active:
            raise AssertionError("Thaw() must run before EnsureVisible()")
        self.ensure_calls.append(index)

    # ------------------------------------------------------------------
    def SetFocus(self) -> None:
        if self.freeze_active:
            raise AssertionError("Thaw() must run before SetFocus()")
        self.set_focus_calls += 1

    # ------------------------------------------------------------------
    def selected_indices(self) -> list[int]:
        return list(self._selected)


class FakeListCtrl(_BaseFakeList):
    """Fake ``wx.ListCtrl`` without native ``SelectAll`` support."""

    pass


class FakeListCtrlWithSelectAll(_BaseFakeList):
    """Fake list control exposing a native ``SelectAll`` helper."""

    def __init__(self, count: int, selected: list[int] | None = None) -> None:
        super().__init__(count, selected)
        self.select_all_calls = 0

    # ------------------------------------------------------------------
    def SelectAll(self) -> None:
        self.select_all_calls += 1
        self._selected = list(range(self._count))


@pytest.mark.usefixtures("stubbed_list_panel_env")
def test_select_all_freezes_and_updates_missing_items(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    fake_list = FakeListCtrl(count=5, selected=[1, 3])
    panel.list = fake_list  # type: ignore[assignment]

    panel._select_all_requirements()

    assert fake_list.freeze_calls == 1
    assert fake_list.thaw_calls == 1
    assert fake_list.state_calls == [0, 2, 4]
    assert fake_list.selected_indices() == [0, 1, 2, 3, 4]
    assert fake_list.focus_calls == [1]
    assert fake_list.ensure_calls == [1]
    assert fake_list.set_focus_calls == 1


@pytest.mark.usefixtures("stubbed_list_panel_env")
def test_select_all_skips_when_everything_selected(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    fake_list = FakeListCtrl(count=3, selected=[0, 1, 2])
    panel.list = fake_list  # type: ignore[assignment]

    panel._select_all_requirements()

    assert fake_list.state_calls == []
    assert fake_list.freeze_calls == 0
    assert fake_list.thaw_calls == 0
    assert fake_list.selected_indices() == [0, 1, 2]


@pytest.mark.usefixtures("stubbed_list_panel_env")
def test_select_all_prefers_native_helper(stubbed_list_panel_env):
    env = stubbed_list_panel_env
    panel = env.create_panel()
    fake_list = FakeListCtrlWithSelectAll(count=4, selected=[2])
    panel.list = fake_list  # type: ignore[assignment]

    panel._select_all_requirements()

    assert fake_list.select_all_calls == 1
    assert fake_list.freeze_calls == 0
    assert fake_list.thaw_calls == 0
    assert fake_list.selected_indices() == [0, 1, 2, 3]
    assert fake_list.focus_calls == [2]
    assert fake_list.ensure_calls == [2]
    assert fake_list.set_focus_calls == 1
