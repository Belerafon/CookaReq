"""Segment-oriented transcript rendering for the agent chat panel."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, TYPE_CHECKING

import wx
from wx.lib.scrolledpanel import ScrolledPanel

from ...i18n import _
from ..helpers import dip
from .components.segments import TurnCard
from .view_model import (
    ConversationTimeline,
    TranscriptEntry,
    build_conversation_timeline,
    build_entry_segments,
    agent_turn_event_signature,
)

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from ..chat_entry import ChatConversation, ChatEntry
else:  # pragma: no cover - runtime avoids circular import
    ChatConversation = Any  # type: ignore[assignment]
    ChatEntry = Any  # type: ignore[assignment]


@lru_cache(maxsize=1)
def _chat_entry_cls():  # pragma: no cover - trivial cache wrapper
    from ..chat_entry import ChatEntry as _ChatEntry

    return _ChatEntry


def _entry_event_signature(entry: TranscriptEntry | None) -> tuple[Any, ...] | None:
    turn = entry.agent_turn if entry is not None else None
    if turn is None:
        return None
    if turn.event_signature:
        return tuple(turn.event_signature)
    return agent_turn_event_signature(turn.events)


def _detect_dirty_entries(
    cache: _ConversationRenderCache,
    entry_lookup: Mapping[str, TranscriptEntry],
    entry_ids: Iterable[str] | None,
    *,
    entry_order: Sequence[str] | None = None,
) -> list[str]:
    requested: list[str] = []
    for entry_id in entry_ids or ():
        if entry_id not in requested:
            requested.append(entry_id)

    desired_order = list(entry_order) if entry_order is not None else list(entry_lookup)
    dirty: set[str] = set(requested)

    for entry_id in desired_order:
        signature = _entry_event_signature(entry_lookup.get(entry_id))
        cached_signature = cache.entry_signatures.get(entry_id)
        if signature != cached_signature:
            dirty.add(entry_id)

    return [entry_id for entry_id in desired_order if entry_id in dirty]


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
        """Store controller hooks consumed by :class:`SegmentListView`."""
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
    entry_signatures: dict[str, tuple[Any, ...] | None] = field(
        default_factory=dict
    )

    def __contains__(self, entry_id: str) -> bool:
        return entry_id in self.cards_by_entry or entry_id in self.entry_snapshots

    @property
    def panels_by_entry(self) -> dict[str, TurnCard]:
        """Backward compatible alias exposing rendered panels by entry id."""
        return self.cards_by_entry


class SegmentListView:
    """Render chat conversations as a list of turn cards."""

    def __init__(
        self,
        owner: wx.Window,
        panel: ScrolledPanel,
        sizer: wx.BoxSizer,
        *,
        callbacks: SegmentViewCallbacks,
    ) -> None:
        """Initialise the transcript view wrappers for *owner* widgets."""
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

    # ------------------------------------------------------------------
    def render(self) -> None:
        """Force a synchronous refresh for the active conversation."""
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
        """Throttle timeline updates while merging redundant requests."""
        if timeline is not None:
            self._pending_timeline = timeline
        elif conversation is None:
            self._pending_timeline = None
        if force:
            self._pending_force = True
        if updated_entries:
            self._pending_entry_ids.update(updated_entries)
        if not self._pending_scheduled:
            self._pending_scheduled = True
            wx.CallAfter(self._flush_pending_updates)

    # ------------------------------------------------------------------
    def render_now(
        self,
        *,
        conversation: ChatConversation | None = None,
        timeline: ConversationTimeline | None = None,
        updated_entries: Iterable[str] | None = None,
        force: bool = False,
    ) -> None:
        """Render the transcript immediately without queuing a UI callback."""

        if timeline is None and conversation is not None:
            timeline = build_conversation_timeline(conversation)

        entry_ids = list(updated_entries or ())
        self._pending_timeline = None
        self._pending_entry_ids.clear()
        self._pending_force = False
        self._pending_scheduled = False
        self._apply_timeline(conversation, timeline, entry_ids, force)

    # ------------------------------------------------------------------
    def forget_conversations(self, conversation_ids: Iterable[str]) -> None:
        """Destroy cached widgets for conversations not tracked anymore."""
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
            cache.entry_signatures.clear()
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
        """Remove cached data for conversations missing from *conversation_ids*."""
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
        elif timeline is None or (
            timeline.conversation_id != conversation.conversation_id
        ):
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
        needs_layout = False

        if conversation is None or timeline is None:
            self._pending_timeline = None
            self._detach_active_conversation()
            self._show_start_placeholder()
            needs_layout = True
        elif not timeline.entries:
            self._pending_timeline = timeline
            self._show_empty_conversation(conversation)
            needs_layout = True
        else:
            self._pending_timeline = timeline
            has_entries = True
            if self._active_conversation_id != timeline.conversation_id:
                force = True
            if force:
                self._detach_active_conversation()
                needs_layout = True
            if self._current_placeholder is not None:
                needs_layout = True
            self._clear_current_placeholder()
            last_card, changed = self._update_conversation_cards(
                conversation, timeline, entry_ids, force
            )
            needs_layout = needs_layout or changed

        if needs_layout:
            panel.Layout()
            panel.FitInside()
            panel.SetupScrolling(scroll_x=False, scroll_y=True)
        if last_card is not None:
            self._scroll_to_bottom(last_card)
        self._callbacks.update_copy_buttons(has_entries)
        self._callbacks.update_header()

    # ------------------------------------------------------------------
    def _update_conversation_cards(
        self,
        conversation: ChatConversation,
        timeline: ConversationTimeline,
        entry_ids: Sequence[str],
        force: bool,
    ) -> tuple[wx.Window | None, bool]:
        conversation_id = timeline.conversation_id
        cache = self._conversation_cache.setdefault(
            conversation_id, _ConversationRenderCache()
        )
        self._active_conversation_id = conversation_id

        desired_order = [entry.entry_id for entry in timeline.entries]
        entry_lookup = {entry.entry_id: entry for entry in timeline.entries}
        dirty_entry_ids = _detect_dirty_entries(
            cache,
            entry_lookup,
            entry_ids,
            entry_order=desired_order,
        )

        if force:
            reuse_cards = cache.order == desired_order and bool(desired_order)
            if reuse_cards:
                regenerate_enabled = not self._callbacks.is_running()
                cards: list[TurnCard] = []
                for entry_id in desired_order:
                    snapshot = cache.entry_snapshots.get(entry_id)
                    card = cache.cards_by_entry.get(entry_id)
                    timeline_entry = entry_lookup.get(entry_id)
                    if (
                        snapshot != timeline_entry
                        or card is None
                        or not self._is_window_alive(card)
                    ):
                        reuse_cards = False
                        break
                    cards.append(card)
                if reuse_cards:
                    for card in cards:
                        card.enable_regenerate(regenerate_enabled)
                    self._attach_cards_in_order(cards)
                    return (cards[-1] if cards else None, True)
            return self._render_full_conversation(conversation, timeline, cache)

        if cache.order != desired_order:
            appended = self._try_append_entries(
                cache,
                timeline.conversation_id,
                desired_order,
                entry_lookup,
                dirty_entry_ids,
            )
            if appended is not None:
                return appended
            return self._render_full_conversation(conversation, timeline, cache)

        if not dirty_entry_ids:
            return None, False

        last_card: wx.Window | None = None
        changed = False

        for entry_id in dirty_entry_ids:
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
            self._cache_entry_snapshot(cache, entry_id, timeline_entry)
            last_card = card
            changed = True

        return last_card, changed

    # ------------------------------------------------------------------
    def _render_full_conversation(
        self,
        conversation: ChatConversation,
        timeline: ConversationTimeline,
        cache: _ConversationRenderCache,
    ) -> tuple[wx.Window | None, bool]:
        panel = self._panel
        panel.Freeze()
        try:
            ordered_cards: list[tuple[str, TurnCard]] = []
            for entry in timeline.entries:
                entry_id = entry.entry_id
                card = cache.cards_by_entry.get(entry_id)
                if card is None or not self._is_window_alive(card):
                    card = TurnCard(
                        self._panel,
                        entry_id=entry_id,
                        entry_index=entry.entry_index,
                        on_layout_hint=self._make_hint_recorder(entry.entry),
                    )
                    card.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self._on_pane_toggled)
                    cache.cards_by_entry[entry_id] = card
                segments = build_entry_segments(entry)
                regenerate_callback = self._build_regenerate_callback(
                    timeline.conversation_id, entry
                )
                card.update(
                    segments=segments,
                    on_regenerate=regenerate_callback,
                    regenerate_enabled=not self._callbacks.is_running(),
                )
                self._cache_entry_snapshot(cache, entry_id, entry)
                ordered_cards.append((entry_id, card))

            keep = {key for key, _ in ordered_cards}
            for stale_key in list(cache.cards_by_entry.keys()):
                if stale_key in keep:
                    continue
                card = cache.cards_by_entry.pop(stale_key)
                cache.entry_snapshots.pop(stale_key, None)
                cache.entry_signatures.pop(stale_key, None)
                if self._is_window_alive(card):
                    if card.GetContainingSizer() is self._sizer:
                        self._sizer.Detach(card)
                    card.Destroy()

            cache.order = [key for key, _ in ordered_cards]
            cache.entry_snapshots = {}
            cache.entry_signatures = {}
            for entry in timeline.entries:
                self._cache_entry_snapshot(cache, entry.entry_id, entry)
            cards = [card for _, card in ordered_cards]
            self._attach_cards_in_order(cards)
            return (cards[-1] if cards else None, True)
        finally:
            panel.Thaw()

    # ------------------------------------------------------------------
    def _try_append_entries(
        self,
        cache: _ConversationRenderCache,
        conversation_id: str,
        desired_order: Sequence[str],
        entry_lookup: Mapping[str, TranscriptEntry],
        entry_ids: Sequence[str] | None,
    ) -> tuple[wx.Window | None, bool] | None:
        current_order = cache.order
        if not desired_order:
            return (None, False) if not current_order else None
        if current_order and desired_order[: len(current_order)] != list(current_order):
            return None
        start_index = len(current_order)
        if start_index > len(desired_order):
            return None
        new_ids = desired_order[start_index:]
        if not current_order and start_index == 0 and not new_ids:
            return (None, False)
        if not new_ids:
            # order mismatch that we cannot reconcile incrementally
            return None

        panel = self._panel
        panel.Freeze()
        try:
            last_card: wx.Window | None = None
            changed = False
            refresh_ids = [
                entry_id
                for entry_id in (entry_ids or ())
                if entry_id in cache.cards_by_entry
            ]
            for entry_id in refresh_ids:
                timeline_entry = entry_lookup.get(entry_id)
                card = cache.cards_by_entry.get(entry_id)
                if (
                    timeline_entry is None
                    or card is None
                    or not self._is_window_alive(card)
                ):
                    return None
                segments = build_entry_segments(timeline_entry)
                regenerate_callback = self._build_regenerate_callback(
                    conversation_id, timeline_entry
                )
                card.update(
                    segments=segments,
                    on_regenerate=regenerate_callback,
                    regenerate_enabled=not self._callbacks.is_running(),
                )
                self._cache_entry_snapshot(cache, entry_id, timeline_entry)
                last_card = card
                changed = True

            new_cards: list[TurnCard] = []
            for entry_id in new_ids:
                timeline_entry = entry_lookup.get(entry_id)
                if timeline_entry is None:
                    return None
                card = cache.cards_by_entry.get(entry_id)
                if card is None or not self._is_window_alive(card):
                    card = TurnCard(
                        self._panel,
                        entry_id=entry_id,
                        entry_index=timeline_entry.entry_index,
                        on_layout_hint=self._make_hint_recorder(
                            timeline_entry.entry
                        ),
                    )
                    card.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self._on_pane_toggled)
                    cache.cards_by_entry[entry_id] = card
                segments = build_entry_segments(timeline_entry)
                regenerate_callback = self._build_regenerate_callback(
                    conversation_id, timeline_entry
                )
                card.update(
                    segments=segments,
                    on_regenerate=regenerate_callback,
                    regenerate_enabled=not self._callbacks.is_running(),
                )
                self._cache_entry_snapshot(cache, entry_id, timeline_entry)
                new_cards.append(card)

            if not new_cards:
                return (last_card, changed)

            cache.order = list(desired_order)
            for card in new_cards:
                if card.GetContainingSizer() is not self._sizer:
                    self._sizer.Add(card, 0, wx.EXPAND)
                card.Show()

            return (new_cards[-1], True)
        finally:
            panel.Thaw()

    # ------------------------------------------------------------------
    def _attach_cards_in_order(self, cards: Sequence[TurnCard]) -> None:
        children: list[wx.Window] = []
        index_lookup: dict[wx.Window, int] = {}
        for child in self._sizer.GetChildren():
            window = child.GetWindow()
            if window is None:
                continue
            index_lookup[window] = len(children)
            children.append(window)

        def _refresh_lookup(start_index: int) -> None:
            for offset in range(start_index, len(children)):
                index_lookup[children[offset]] = offset

        for desired_index, card in enumerate(cards):
            if card.GetContainingSizer() is self._sizer:
                current_index = index_lookup.get(card, -1)
                if current_index != desired_index:
                    self._sizer.Detach(card)
                    self._sizer.Insert(desired_index, card, 0, wx.EXPAND)
                    if current_index >= 0:
                        children.pop(current_index)
                    children.insert(desired_index, card)
                    refresh_from = desired_index if current_index < 0 else min(
                        desired_index, current_index
                    )
                    _refresh_lookup(refresh_from)
            else:
                self._sizer.Insert(desired_index, card, 0, wx.EXPAND)
                children.insert(desired_index, card)
                _refresh_lookup(desired_index)
            card.Show()

        keep = set(cards)
        for child in list(self._sizer.GetChildren()):
            window = child.GetWindow()
            if window is None or window in keep:
                continue
            self._sizer.Detach(window)
            if self._is_window_alive(window):
                window.Hide()

    # ------------------------------------------------------------------
    @staticmethod
    def _cache_entry_snapshot(
        cache: _ConversationRenderCache, entry_id: str, entry: TranscriptEntry
    ) -> None:
        cache.entry_snapshots[entry_id] = entry
        cache.entry_signatures[entry_id] = _entry_event_signature(entry)

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
            updated = dict(hints) if isinstance(hints, Mapping) else {}
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
        with suppress(RuntimeError):
            if placeholder.GetContainingSizer() is self._sizer:
                self._sizer.Detach(placeholder)
        placeholder.Hide()
        with suppress(RuntimeError):
            placeholder.Destroy()
        if placeholder is self._start_placeholder:
            self._start_placeholder = None
        for cache in self._conversation_cache.values():
            if cache.placeholder is placeholder:
                cache.placeholder = None
        self._current_placeholder = None

    # ------------------------------------------------------------------
    def _scroll_to_bottom(self, target: wx.Window | None) -> None:
        self._apply_scroll(target)
        wx.CallAfter(self._apply_scroll, target)

    # ------------------------------------------------------------------
    def _apply_scroll(self, target: wx.Window | None) -> None:
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
        if window is None:
            panel.ScrollChildIntoView(panel)

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
        if not isinstance(chat_entry, _chat_entry_cls()):
            return None

        def _callback(entry_ref: ChatEntry = chat_entry) -> None:
            self._callbacks.on_regenerate(conversation_id, entry_ref)

        return _callback


__all__ = ["SegmentViewCallbacks", "SegmentListView"]
