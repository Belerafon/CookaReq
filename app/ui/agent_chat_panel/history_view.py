"""UI helpers for rendering and interacting with the chat history list."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import NamedTuple

import wx
import wx.dataview as dv

from ...i18n import _
from ..chat_entry import ChatConversation


class HistoryInteractionPreparation(NamedTuple):
    """Describe whether an interaction can proceed and if the view refreshed."""

    allowed: bool
    refreshed: bool


class HistoryView:
    """Encapsulate DataViewListCtrl operations for the history sidebar."""

    def __init__(
        self,
        list_ctrl: dv.DataViewListCtrl,
        *,
        get_conversations: Callable[[], Sequence[ChatConversation]],
        format_row: Callable[[ChatConversation], Sequence[str]],
        get_active_index: Callable[[], int | None],
        activate_conversation: Callable[[int], None],
        handle_delete_request: Callable[[Sequence[int]], None],
        is_running: Callable[[], bool],
        splitter: wx.SplitterWindow,
        prepare_interaction: Callable[[], bool] | None = None,
    ) -> None:
        self._list = list_ctrl
        self._get_conversations = get_conversations
        self._format_row = format_row
        self._get_active_index = get_active_index
        self._activate_conversation = activate_conversation
        self._handle_delete_request = handle_delete_request
        self._is_running = is_running
        self._splitter = splitter
        self._prepare_interaction = prepare_interaction
        self._suppress_selection = False
        self._sash_goal: int | None = None
        self._sash_dirty = False
        self._last_sash = 0
        self._internal_adjust = 0
        self._bind_events()

    # ------------------------------------------------------------------
    def _bind_events(self) -> None:
        self._list.Bind(dv.EVT_DATAVIEW_SELECTION_CHANGED, self._on_select_history)
        self._list.Bind(dv.EVT_DATAVIEW_ITEM_CONTEXT_MENU, self._on_history_item_context_menu)
        self._list.Bind(wx.EVT_CONTEXT_MENU, self._on_history_context_menu)
        binder = getattr(self._list, "bind_after_left_down", None)
        if callable(binder):
            binder(self._on_mouse_down)
        else:
            self._list.Bind(wx.EVT_LEFT_DOWN, self._on_mouse_down)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        """Repopulate the history list from the callbacks."""

        conversations = self._get_conversations()
        self._list.Freeze()
        self._suppress_selection = True
        try:
            self._list.DeleteAllItems()
            active_index = self._get_active_index()
            for conversation in conversations:
                row = self._format_row(conversation)
                self._list.AppendItem(list(row))
            if (
                active_index is not None
                and 0 <= active_index < self._list.GetItemCount()
            ):
                self._list.SelectRow(active_index)
                self.ensure_visible(active_index)
            else:
                self._list.UnselectAll()
        finally:
            self._suppress_selection = False
            self._list.Thaw()

    # ------------------------------------------------------------------
    def ensure_visible(self, index: int) -> None:
        if not (0 <= index < self._list.GetItemCount()):
            return
        item = self._list.RowToItem(index)
        if item.IsOk():
            self._list.EnsureVisible(item)

    # ------------------------------------------------------------------
    def selected_rows(self) -> list[int]:
        selections = self._list.GetSelections()
        rows: list[int] = []
        for item in selections:
            if not item.IsOk():
                continue
            row = self._list.ItemToRow(item)
            if row != wx.NOT_FOUND:
                rows.append(row)
        if not rows:
            item = self._list.GetSelection()
            if item and item.IsOk():
                row = self._list.ItemToRow(item)
                if row != wx.NOT_FOUND:
                    rows.append(row)
        rows.sort()
        return rows

    # ------------------------------------------------------------------
    def on_splitter_size(self, event: wx.SizeEvent) -> None:
        event.Skip()
        if self._sash_goal is None:
            return
        if not self._splitter or not self._splitter.IsSplit():
            return
        current = self._splitter.GetSashPosition()
        if not self._sash_dirty and abs(current - self._sash_goal) <= 1:
            return
        self._sash_dirty = True
        self._apply_sash_if_ready()

    # ------------------------------------------------------------------
    def on_sash_changed(self, event: wx.SplitterEvent) -> None:
        splitter = self._splitter
        if splitter is None or event.GetEventObject() is not splitter:
            event.Skip()
            return
        if self._internal_adjust > 0:
            event.Skip()
            return
        pos = splitter.GetSashPosition()
        self._last_sash = max(pos, 0)
        self._sash_goal = pos
        self._sash_dirty = False
        event.Skip()

    # ------------------------------------------------------------------
    def history_sash(self) -> int:
        splitter = self._splitter
        if splitter and splitter.IsSplit():
            pos = splitter.GetSashPosition()
            if pos > 0:
                self._last_sash = pos
        return max(self._last_sash, 0)

    # ------------------------------------------------------------------
    def default_history_sash(self) -> int:
        splitter = self._splitter
        if splitter and splitter.IsSplit():
            pos = splitter.GetSashPosition()
            if pos > 0:
                return pos
            return splitter.GetMinimumPaneSize()
        return max(self._last_sash, 0)

    # ------------------------------------------------------------------
    def apply_history_sash(self, value: int) -> None:
        target = max(int(value), 0)
        self._sash_goal = target
        self._last_sash = max(target, 0)
        self._sash_dirty = True
        self._apply_sash_if_ready()

    # ------------------------------------------------------------------
    def _apply_sash_if_ready(self) -> None:
        target = self._sash_goal
        if target is None:
            self._sash_dirty = False
            return
        splitter = self._splitter
        if splitter is None or not splitter.IsSplit():
            return
        size = splitter.GetClientSize()
        if size.width <= 0:
            return
        desired = max(target, splitter.GetMinimumPaneSize())
        if not self._attempt_set_sash(desired):
            self._sash_dirty = True
            return
        self._sash_dirty = False
        wx.CallAfter(self._verify_sash_after_apply)

    # ------------------------------------------------------------------
    def _attempt_set_sash(self, target: int) -> bool:
        splitter = self._splitter
        if splitter is None or not splitter.IsSplit():
            return False
        self._internal_adjust += 1
        splitter.SetSashPosition(target)
        actual = splitter.GetSashPosition()
        wx.CallAfter(self._release_sash_adjust)
        self._last_sash = max(actual, 0)
        return abs(actual - target) <= 1

    # ------------------------------------------------------------------
    def _release_sash_adjust(self) -> None:
        if self._internal_adjust > 0:
            self._internal_adjust -= 1

    # ------------------------------------------------------------------
    def _verify_sash_after_apply(self) -> None:
        target = self._sash_goal
        if target is None:
            return
        splitter = self._splitter
        if splitter is None or not splitter.IsSplit():
            return
        current = splitter.GetSashPosition()
        self._last_sash = max(current, 0)
        expected = max(target, splitter.GetMinimumPaneSize())
        if abs(current - expected) <= 1:
            return
        self._sash_dirty = True
        self._apply_sash_if_ready()

    # ------------------------------------------------------------------
    def _ensure_row_selected(self, row: int | None) -> Sequence[int]:
        if row is None:
            return ()
        if not (0 <= row < self._list.GetItemCount()):
            return ()
        selected = set(self.selected_rows())
        if row not in selected:
            try:
                item = self._list.RowToItem(row)
            except (AttributeError, RuntimeError):
                item = None
            if item and item.IsOk():
                self._list.UnselectAll()
                self._list.Select(item)
            selected = set(self.selected_rows())
        return tuple(sorted(selected))

    # ------------------------------------------------------------------
    def _on_history_item_context_menu(self, event: dv.DataViewEvent) -> None:
        if event.GetEventObject() is not self._list:
            event.Skip()
            return
        item = event.GetItem()
        row = None
        if item and item.IsOk():
            row = self._list.ItemToRow(item)
        self._show_context_menu(row)

    # ------------------------------------------------------------------
    def _on_history_context_menu(self, event: wx.ContextMenuEvent) -> None:
        if event.GetEventObject() is not self._list:
            event.Skip()
            return
        pos = event.GetPosition()
        row = None
        if pos != wx.DefaultPosition:
            client = self._list.ScreenToClient(pos)
            item, _column = self._list.HitTest(client)
            if item and item.IsOk():
                row = self._list.ItemToRow(item)
        self._show_context_menu(row)

    # ------------------------------------------------------------------
    def _show_context_menu(self, row: int | None) -> None:
        preparation = self._prepare_for_interaction()
        if not preparation.allowed:
            return
        rows = self._ensure_row_selected(row)
        if not rows:
            return
        conversations = self._get_conversations()
        if not conversations:
            return
        menu = wx.Menu()
        label = _("Delete chat") if len(rows) == 1 else _("Delete selected chats")
        delete_item = menu.Append(wx.ID_ANY, label)

        def on_delete(event: wx.CommandEvent) -> None:
            event.Skip()
            self._handle_delete_request(rows)

        menu.Bind(wx.EVT_MENU, on_delete, delete_item)
        try:
            self._list.PopupMenu(menu)
        finally:
            menu.Destroy()

    # ------------------------------------------------------------------
    def _on_select_history(self, event: dv.DataViewEvent) -> None:
        if self._suppress_selection:
            event.Skip()
            return
        preparation = self._prepare_for_interaction()
        if not preparation.allowed:
            event.Skip()
            return
        index = self._extract_index(None if preparation.refreshed else event)
        if index is not None:
            self._activate_conversation(index)
        event.Skip()

    # ------------------------------------------------------------------
    def _extract_index(self, event: dv.DataViewEvent | None) -> int | None:
        item = None
        if event is not None:
            item = event.GetItem()
        if item is None or not item.IsOk():
            item = self._list.GetSelection()
        if item is None or not item.IsOk():
            return None
        row = self._list.ItemToRow(item)
        conversations = self._get_conversations()
        if 0 <= row < len(conversations):
            return row
        return None

    # ------------------------------------------------------------------
    def _on_mouse_down(self, event: wx.MouseEvent) -> None:
        preparation = self._prepare_for_interaction()
        if not preparation.allowed:
            event.Skip()
            return
        pos = event.GetPosition()
        item, _column = self._list.HitTest(pos)
        if not item or not item.IsOk():
            self._list.UnselectAll()
            self._list.SetFocus()
            event.Skip()
            return
        row = self._list.ItemToRow(item)
        if row == wx.NOT_FOUND:
            self._list.UnselectAll()
            self._list.SetFocus()
            event.Skip()
            return
        self._suppress_selection = True
        try:
            self._list.SelectRow(row)
            self._list.EnsureVisible(item)
        finally:
            self._suppress_selection = False
        self._activate_conversation(row)
        event.Skip()

    # ------------------------------------------------------------------
    def _prepare_for_interaction(self) -> HistoryInteractionPreparation:
        if self._is_running():
            return HistoryInteractionPreparation(False, False)
        callback = self._prepare_interaction
        if callback is None:
            return HistoryInteractionPreparation(True, False)
        try:
            refreshed = bool(callback())
        except Exception:  # pragma: no cover - defensive guard
            return HistoryInteractionPreparation(False, False)
        return HistoryInteractionPreparation(True, refreshed)


__all__ = ["HistoryInteractionPreparation", "HistoryView"]
