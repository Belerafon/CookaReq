"""Segment-oriented transcript rendering for the agent chat panel."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import logging
import time

import wx
from wx.lib.scrolledpanel import ScrolledPanel

from ...i18n import _
from ..chat_entry import ChatConversation, ChatEntry
from ..helpers import dip
from .components.segments import TurnCard
from .debug_logging import emit_history_debug, get_history_logger
from .view_model import (
    AgentSegment,
    ConversationTimeline,
    TranscriptEntry,
    build_conversation_timeline,
    build_entry_segments,
)


logger = get_history_logger("segment_view")


class SegmentViewCallbacks:
    """Callback bundle consumed by :class:`SegmentListView`."""

    def __init__(
        self,
        *,
        get_conversation: Callable[[], ChatConversation | None],
        is_running: Callable[[], bool],
        on_regenerate: Callable[[str, ChatEntry], None],
        update_copy_buttons: Callable[[bool], None],
        update_header: Callable[[], None],
    ) -> None:
        self.get_conversation = get_conversation
        self.is_running = is_running
        self.on_regenerate = on_regenerate
        self.update_copy_buttons = update_copy_buttons
        self.update_header = update_header


@dataclass(slots=True)
class _ConversationRenderCache:
    cards_by_entry: dict[str, TurnCard] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    placeholder: wx.Window | None = None
    entry_snapshots: dict[str, TranscriptEntry] = field(default_factory=dict)


class SegmentListView:
    """Render chat conversations as a list of turn cards."""

    _SLOW_ENTRY_THRESHOLD_NS = 5_000_000
    _MAX_SLOW_ENTRIES = 5

    def __init__(
        self,
        owner: wx.Window,
        panel: ScrolledPanel,
        sizer: wx.BoxSizer,
        *,
        callbacks: SegmentViewCallbacks,
    ) -> None:
        self._owner = owner
        self._panel = panel
        self._sizer = sizer
        self._callbacks = callbacks
        self._conversation_cache: dict[str, _ConversationRenderCache] = {}
        self._active_conversation_id: str | None = None
        self._current_placeholder: wx.Window | None = None
        self._start_placeholder: wx.Window | None = None
        self._pending_timeline: ConversationTimeline | None = None
        self._pending_entry_ids: set[str] = set()
        self._pending_force: bool = False
        self._pending_scheduled = False
        self._last_render_completed_ns: int | None = None

    # ------------------------------------------------------------------
    def render(self) -> None:
        conversation = self._callbacks.get_conversation()
        timeline = (
            build_conversation_timeline(conversation)
            if conversation is not None
            else None
        )
        self.schedule_render(
            conversation=conversation,
            timeline=timeline,
            force=True,
        )
        self._flush_pending_updates()

    # ------------------------------------------------------------------
    def schedule_render(
        self,
        *,
        conversation: ChatConversation | None = None,
        timeline: ConversationTimeline | None = None,
        updated_entries: Iterable[str] | None = None,
        force: bool = False,
    ) -> None:
        pending_timeline_id = (
            timeline.conversation_id if timeline is not None else None
        )
        conversation_id = None
        if conversation is not None:
            conversation_id = conversation.conversation_id
        elif pending_timeline_id is not None:
            conversation_id = pending_timeline_id
        entry_ids: tuple[str, ...] | None = None
        if updated_entries is not None:
            entry_ids = tuple(updated_entries)
        if timeline is not None:
            self._pending_timeline = timeline
        elif conversation is None:
            self._pending_timeline = None
        if force:
            self._pending_force = True
        if entry_ids:
            self._pending_entry_ids.update(entry_ids)
        if not self._pending_scheduled:
            self._pending_scheduled = True
            wx.CallAfter(self._flush_pending_updates)

    # ------------------------------------------------------------------
    def forget_conversations(self, conversation_ids: Iterable[str]) -> None:
        for conversation_id in list(conversation_ids):
            cache = self._conversation_cache.pop(conversation_id, None)
            if cache is None:
                continue
            for card in cache.cards_by_entry.values():
                if self._is_window_alive(card):
                    if card.GetContainingSizer() is self._sizer:
                        self._sizer.Detach(card)
                    card.Destroy()
            cache.cards_by_entry.clear()
            cache.order.clear()
            cache.entry_snapshots.clear()
            placeholder = cache.placeholder
            if self._is_window_alive(placeholder):
                if placeholder.GetContainingSizer() is self._sizer:
                    self._sizer.Detach(placeholder)
                placeholder.Destroy()
            if self._active_conversation_id == conversation_id:
                self._active_conversation_id = None
                self._clear_current_placeholder()

    # ------------------------------------------------------------------
    def sync_known_conversations(self, conversation_ids: Iterable[str]) -> None:
        known = set(conversation_ids)
        obsolete = [
            conversation_id
            for conversation_id in self._conversation_cache
            if conversation_id not in known
        ]
        if obsolete:
            self.forget_conversations(obsolete)

    # ------------------------------------------------------------------
    def _flush_pending_updates(self) -> None:
        self._pending_scheduled = False
        timeline = self._pending_timeline
        entry_ids = list(self._pending_entry_ids)
        force = self._pending_force
        self._pending_entry_ids.clear()
        self._pending_force = False


        conversation = self._callbacks.get_conversation()
        if conversation is None:
            timeline = None
        elif timeline is None or timeline.conversation_id != conversation.conversation_id:
            timeline = build_conversation_timeline(conversation)
        self._apply_timeline(conversation, timeline, entry_ids, force)


    # ------------------------------------------------------------------
    def _apply_timeline(
        self,
        conversation: ChatConversation | None,
        timeline: ConversationTimeline | None,
        entry_ids: Sequence[str],
        force: bool,
    ) -> None:
        panel = self._panel
        last_card: wx.Window | None = None
        has_entries = False
        conversation_id = conversation.conversation_id if conversation else None

        if conversation is None or timeline is None:
            self._pending_timeline = None
            self._detach_active_conversation()
            self._show_start_placeholder()
        elif not timeline.entries:
            self._pending_timeline = timeline
            self._show_empty_conversation(conversation)
        else:
            self._pending_timeline = timeline
            has_entries = True
            if self._active_conversation_id != timeline.conversation_id:
                force = True
            if force:
                self._detach_active_conversation()
            self._clear_current_placeholder()
            last_card = self._update_conversation_cards(
                conversation, timeline, entry_ids, force
            )

        panel.Layout()
        panel.FitInside()
        panel.SetupScrolling(scroll_x=False, scroll_y=True)
        if last_card is not None:
            self._scroll_to_bottom(last_card)
        self._callbacks.update_copy_buttons(has_entries)
        self._callbacks.update_header()
        self._last_render_completed_ns = time.perf_counter_ns()

    # ------------------------------------------------------------------
    def _update_conversation_cards(
        self,
        conversation: ChatConversation,
        timeline: ConversationTimeline,
        entry_ids: Sequence[str],
        force: bool,
    ) -> wx.Window | None:
        conversation_id = timeline.conversation_id
        cache = self._conversation_cache.setdefault(
            conversation_id, _ConversationRenderCache()
        )
        self._active_conversation_id = conversation_id

        desired_order = [entry.entry_id for entry in timeline.entries]
        if force or cache.order != desired_order:
            return self._render_full_conversation(conversation, timeline, cache)

        if not entry_ids:
            return None

        entry_lookup = {entry.entry_id: entry for entry in timeline.entries}
        last_card: wx.Window | None = None
        updated = 0

        for entry_id in entry_ids:
            timeline_entry = entry_lookup.get(entry_id)
            if timeline_entry is None:
                return self._render_full_conversation(conversation, timeline, cache)
            card = cache.cards_by_entry.get(entry_id)
            if card is None or not self._is_window_alive(card):
                return self._render_full_conversation(conversation, timeline, cache)
            previous_snapshot = cache.entry_snapshots.get(entry_id)
            if previous_snapshot == timeline_entry:
                continue
            segments = build_entry_segments(timeline_entry)
            regenerate_callback = self._build_regenerate_callback(
                conversation_id, timeline_entry
            )
            card.update(
                segments=segments,
                on_regenerate=regenerate_callback,
                regenerate_enabled=not self._callbacks.is_running(),
            )
            cache.entry_snapshots[entry_id] = timeline_entry
            last_card = card
            updated += 1


        return last_card

    # ------------------------------------------------------------------
    def _render_full_conversation(
        self,
        conversation: ChatConversation,
        timeline: ConversationTimeline,
        cache: _ConversationRenderCache,
    ) -> wx.Window | None:
        conversation_id = conversation.conversation_id
        panel = self._panel
        render_start_ns = time.perf_counter_ns()
        freeze_ns = 0
        thaw_ns = 0
        attach_elapsed_ns = 0
        destroy_elapsed_ns = 0
        slow_entries: list[dict[str, object]] = []
        new_cards = 0
        reused_cards = 0
        removed_cards = 0
        entry_processing_ns = 0
        attach_stats: dict[str, int] = {
            "attached": 0,
            "moved": 0,
            "kept": 0,
            "hidden": 0,
        }
        emit_history_debug(
            logger,
            "segment_view.render.start",
            conversation_id=conversation_id,
            entry_count=len(timeline.entries),
        )
        freeze_start_ns = time.perf_counter_ns()
        panel.Freeze()
        freeze_ns = time.perf_counter_ns() - freeze_start_ns
        try:
            ordered_cards: list[tuple[str, TurnCard]] = []
            for entry_index, entry in enumerate(timeline.entries, start=1):
                entry_id = entry.entry_id
                entry_start_ns = time.perf_counter_ns()
                create_elapsed_ns: int | None = None
                created = False
                card = cache.cards_by_entry.get(entry_id)
                if card is None or not self._is_window_alive(card):
                    create_start = time.perf_counter_ns()
                    card = TurnCard(
                        self._panel,
                        entry_id=entry_id,
                        entry_index=entry.entry_index,
                        on_layout_hint=self._make_hint_recorder(entry.entry),
                    )
                    card.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self._on_pane_toggled)
                    cache.cards_by_entry[entry_id] = card
                    new_cards += 1
                    create_elapsed_ns = time.perf_counter_ns() - create_start
                    created = True
                else:
                    reused_cards += 1
                segments_start_ns = time.perf_counter_ns()
                segments = build_entry_segments(entry)
                segments_ns = time.perf_counter_ns() - segments_start_ns
                update_start_ns = time.perf_counter_ns()
                regenerate_callback = self._build_regenerate_callback(
                    timeline.conversation_id, entry
                )
                card.update(
                    segments=segments,
                    on_regenerate=regenerate_callback,
                    regenerate_enabled=not self._callbacks.is_running(),
                )
                update_ns = time.perf_counter_ns() - update_start_ns
                entry_total_ns = time.perf_counter_ns() - entry_start_ns
                entry_processing_ns += entry_total_ns
                cache.entry_snapshots[entry_id] = entry
                ordered_cards.append((entry_id, card))
                if entry_total_ns >= self._SLOW_ENTRY_THRESHOLD_NS:
                    slow_entries.append(
                        {
                            "entry_id": entry_id,
                            "total_ns": entry_total_ns,
                            "segments_ns": segments_ns,
                            "update_ns": update_ns,
                            "card_create_ns": create_elapsed_ns,
                        }
                    )
                emit_history_debug(
                    logger,
                    "segment_view.render.entry",
                    conversation_id=conversation_id,
                    entry_id=entry_id,
                    entry_index=entry.entry_index,
                    order_index=entry_index - 1,
                    created=created,
                    create_ns=create_elapsed_ns,
                    segments_ns=segments_ns,
                    update_ns=update_ns,
                    total_ns=entry_total_ns,
                )

            keep = {key for key, _ in ordered_cards}
            destroy_start_ns = time.perf_counter_ns()
            for stale_key in list(cache.cards_by_entry.keys()):
                if stale_key in keep:
                    continue
                card = cache.cards_by_entry.pop(stale_key)
                cache.entry_snapshots.pop(stale_key, None)
                if self._is_window_alive(card):
                    if card.GetContainingSizer() is self._sizer:
                        self._sizer.Detach(card)
                    card.Destroy()
                    removed_cards += 1
            destroy_elapsed_ns = time.perf_counter_ns() - destroy_start_ns
            if removed_cards:
                emit_history_debug(
                    logger,
                    "segment_view.render.cleanup",
                    conversation_id=conversation_id,
                    removed_cards=removed_cards,
                    destroy_ns=destroy_elapsed_ns,
                )

            cache.order = [key for key, _ in ordered_cards]
            cache.entry_snapshots = {entry.entry_id: entry for entry in timeline.entries}
            cards = [card for _, card in ordered_cards]
            attach_start_ns = time.perf_counter_ns()
            attach_stats = self._attach_cards_in_order(cards)
            attach_elapsed_ns = time.perf_counter_ns() - attach_start_ns
            emit_history_debug(
                logger,
                "segment_view.render.attach",
                conversation_id=conversation_id,
                card_count=len(cards),
                attach_ns=attach_elapsed_ns,
                **attach_stats,
            )
            return cards[-1] if cards else None
        finally:
            thaw_start_ns = time.perf_counter_ns()
            panel.Thaw()
            thaw_ns = time.perf_counter_ns() - thaw_start_ns
            total_elapsed_ns = time.perf_counter_ns() - render_start_ns
            slow_entries.sort(key=lambda item: item["total_ns"], reverse=True)
            emit_history_debug(
                logger,
                "segment_view.render.summary",
                conversation_id=conversation_id,
                entry_count=len(timeline.entries),
                new_cards=new_cards,
                reused_cards=reused_cards,
                removed_cards=removed_cards,
                total_ns=total_elapsed_ns,
                freeze_ns=freeze_ns,
                thaw_ns=thaw_ns,
                attach_ns=attach_elapsed_ns,
                destroy_ns=destroy_elapsed_ns,
                entry_processing_ns=entry_processing_ns,
                attach_stats=attach_stats,
                slow_entries=slow_entries[: self._MAX_SLOW_ENTRIES],
            )

    # ------------------------------------------------------------------
    def _attach_cards_in_order(self, cards: Sequence[TurnCard]) -> dict[str, int]:
        existing_children = [child.GetWindow() for child in self._sizer.GetChildren()]
        moved = 0
        attached = 0
        kept = 0
        hidden = 0
        for index, card in enumerate(cards):
            if card.GetContainingSizer() is self._sizer:
                try:
                    current_index = existing_children.index(card)
                except ValueError:
                    current_index = -1
                if current_index != index:
                    self._sizer.Detach(card)
                    self._sizer.Insert(index, card, 0, wx.EXPAND)
                    moved += 1
                else:
                    kept += 1
            else:
                self._sizer.Insert(index, card, 0, wx.EXPAND)
                attached += 1
            card.Show()
        keep = set(cards)
        for child in list(self._sizer.GetChildren()):
            window = child.GetWindow()
            if window is None or window in keep:
                continue
            self._sizer.Detach(window)
            if self._is_window_alive(window):
                window.Hide()
                hidden += 1
        return {
            "attached": attached,
            "moved": moved,
            "kept": kept,
            "hidden": hidden,
        }
    # ------------------------------------------------------------------
    def _make_hint_recorder(self, entry: ChatEntry) -> Callable[[str, int], None]:
        def _record_hint(hint_key: str, width: int) -> None:
            try:
                numeric_width = int(width)
            except (TypeError, ValueError):
                return
            if numeric_width <= 0:
                return
            hints = entry.layout_hints
            if isinstance(hints, Mapping):
                updated = dict(hints)
            else:
                updated = {}
            updated[hint_key] = numeric_width
            entry.layout_hints = updated

        return _record_hint

    # ------------------------------------------------------------------
    def _show_start_placeholder(self) -> None:
        self._clear_current_placeholder()
        placeholder = self._start_placeholder
        if not self._is_window_alive(placeholder):
            placeholder = wx.StaticText(
                self._panel,
                label=_("Start chatting with the agent to see responses here."),
            )
            self._start_placeholder = placeholder
        self._current_placeholder = placeholder
        self._sizer.Add(placeholder, 0, wx.ALL, dip(self._owner, 8))
        placeholder.Show()

    # ------------------------------------------------------------------
    def _show_empty_conversation(self, conversation: ChatConversation) -> None:
        self._detach_active_conversation()
        self._clear_current_placeholder()
        conversation_id = conversation.conversation_id
        cache = self._conversation_cache.setdefault(
            conversation_id, _ConversationRenderCache()
        )
        placeholder = cache.placeholder
        if not self._is_window_alive(placeholder):
            placeholder = wx.StaticText(
                self._panel,
                label=_(
                    "This chat does not have any messages yet. Send one to get started."
                ),
            )
            cache.placeholder = placeholder
        self._active_conversation_id = conversation_id
        self._current_placeholder = placeholder
        self._sizer.Add(placeholder, 0, wx.ALL, dip(self._owner, 8))
        placeholder.Show()

    # ------------------------------------------------------------------
    def _detach_active_conversation(self) -> None:
        conversation_id = self._active_conversation_id
        if conversation_id is None:
            return
        cache = self._conversation_cache.get(conversation_id)
        if cache is not None:
            for card in cache.cards_by_entry.values():
                if not self._is_window_alive(card):
                    continue
                if card.GetContainingSizer() is self._sizer:
                    self._sizer.Detach(card)
                card.Hide()
            placeholder = cache.placeholder
            if self._is_window_alive(placeholder):
                if placeholder.GetContainingSizer() is self._sizer:
                    self._sizer.Detach(placeholder)
                placeholder.Hide()
        self._active_conversation_id = None
        self._clear_current_placeholder()

    # ------------------------------------------------------------------
    def _clear_current_placeholder(self) -> None:
        placeholder = self._current_placeholder
        if not self._is_window_alive(placeholder):
            self._current_placeholder = None
            return
        try:
            if placeholder.GetContainingSizer() is self._sizer:
                self._sizer.Detach(placeholder)
        except RuntimeError:
            pass
        placeholder.Hide()
        try:
            placeholder.Destroy()
        except RuntimeError:
            pass
        if placeholder is self._start_placeholder:
            self._start_placeholder = None
        for cache in self._conversation_cache.values():
            if cache.placeholder is placeholder:
                cache.placeholder = None
        self._current_placeholder = None

    # ------------------------------------------------------------------
    def _scroll_to_bottom(self, target: wx.Window | None) -> None:
        self._apply_scroll(target, "immediate")
        wx.CallAfter(self._apply_scroll, target, "async")

    # ------------------------------------------------------------------
    def _apply_scroll(self, target: wx.Window | None, source: str = "immediate") -> None:
        panel = self._panel
        if not self._is_window_alive(panel):
            return
        panel.Layout()
        panel.FitInside()
        window: wx.Window | None = target if self._is_window_alive(target) else None
        if window is not None and window.GetParent() is not panel:
            window = None
        if window is not None:
            try:
                panel.ScrollChildIntoView(window)
            except RuntimeError:
                window = None
            else:
                rect = window.GetRect()
                client_height = panel.GetClientSize().GetHeight()
                bottom = rect.GetBottom()
                if bottom > client_height:
                    _, ppu_y = panel.GetScrollPixelsPerUnit()
                    if ppu_y <= 0:
                        ppu_y = 1
                    view_x, view_y = panel.GetViewStart()
                    extra_units = (bottom - client_height + ppu_y - 1) // ppu_y
                    panel.Scroll(view_x, view_y + extra_units)
                return
        try:
            panel.ScrollChildIntoView(panel)
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    def _on_pane_toggled(self, _event: wx.CollapsiblePaneEvent) -> None:
        panel = self._panel
        if self._is_window_alive(panel):
            panel.Layout()
            panel.FitInside()

    # ------------------------------------------------------------------
    @staticmethod
    def _is_window_alive(window: wx.Window | None) -> bool:
        return bool(window) and not getattr(window, "__wxPyDeadObject__", False)

    # ------------------------------------------------------------------
    def _build_regenerate_callback(
        self, conversation_id: str, entry: TranscriptEntry
    ) -> Callable[[], None] | None:
        if not entry.can_regenerate:
            return None
        chat_entry = entry.entry
        if not isinstance(chat_entry, ChatEntry):
            return None

        def _callback(entry_ref: ChatEntry = chat_entry) -> None:
            self._callbacks.on_regenerate(conversation_id, entry_ref)

        return _callback


__all__ = ["SegmentViewCallbacks", "SegmentListView"]
