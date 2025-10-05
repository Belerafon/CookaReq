"""Segment-oriented transcript rendering for the agent chat panel."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import logging
import threading
import time

import wx
from wx.lib.scrolledpanel import ScrolledPanel

from ...i18n import _
from ..chat_entry import ChatConversation, ChatEntry
from ..helpers import dip
from .components.segments import TurnCard
from .debug_logging import emit_history_debug, elapsed_ns
from .view_model import (
    AgentSegment,
    ConversationTimeline,
    TranscriptEntry,
    build_conversation_timeline,
    build_entry_segments,
)


logger = logging.getLogger(__name__)


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


class _SegmentViewPollMonitor:
    """Background poller that re-emits render snapshots on a worker thread."""

    def __init__(self, interval_ms: int) -> None:
        self._interval_ms = max(interval_ms, 250)
        self._interval_s = self._interval_ms / 1000.0
        self._lock = threading.Lock()
        self._snapshot: dict[str, object] | None = None
        self._snapshot_ns: int | None = None
        self._stop_event = threading.Event()
        self._trigger_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="AgentChatHistoryPoll",
            daemon=True,
        )
        self._thread.start()
        emit_history_debug(
            logger,
            "segment_view.poll.thread_started",
            interval_ms=self._interval_ms,
        )

    def update(self, snapshot: dict[str, object], source: str) -> None:
        now_ns = time.perf_counter_ns()
        payload = dict(snapshot)
        payload["snapshot_source"] = source
        payload["snapshot_updated_ns"] = now_ns
        with self._lock:
            self._snapshot = payload
            self._snapshot_ns = now_ns
        self._trigger_event.set()

    def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        self._trigger_event.set()
        thread = self._thread
        if thread.is_alive():
            thread.join(timeout=self._interval_s * 2)
        emit_history_debug(
            logger,
            "segment_view.poll.thread_stopped",
            interval_ms=self._interval_ms,
        )

    def _run(self) -> None:
        while True:
            triggered = self._trigger_event.wait(self._interval_s)
            self._trigger_event.clear()
            if self._stop_event.is_set():
                break
            with self._lock:
                if self._snapshot is not None:
                    snapshot = dict(self._snapshot)
                    snapshot_ns = self._snapshot_ns
                else:
                    snapshot = None
                    snapshot_ns = None
            if snapshot is None:
                emit_history_debug(
                    logger,
                    "segment_view.poll.snapshot",
                    poll_reason="monitor_idle",
                    poll_triggered=triggered,
                    snapshot_available=False,
                    interval_ms=self._interval_ms,
                )
                continue
            emit_history_debug(
                logger,
                "segment_view.poll.snapshot",
                poll_reason="monitor_emit",
                poll_triggered=triggered,
                snapshot_available=True,
                interval_ms=self._interval_ms,
                stale_ns=elapsed_ns(snapshot_ns),
                **snapshot,
            )


class SegmentListView:
    """Render chat conversations as a list of turn cards."""

    _DEBUG_POLL_INTERVAL_MS = 3000

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
        self._last_poll_conversation_id: str | None = None
        self._last_poll_card_count = 0
        self._poll_sequence = 0
        self._poll_monitor = _SegmentViewPollMonitor(self._DEBUG_POLL_INTERVAL_MS)
        self._debug_poll_timer = wx.Timer(self._panel)
        self._panel.Bind(wx.EVT_TIMER, self._on_debug_poll_timer, self._debug_poll_timer)
        self._panel.Bind(wx.EVT_WINDOW_DESTROY, self._on_panel_destroy)
        timer_started = self._debug_poll_timer.Start(self._DEBUG_POLL_INTERVAL_MS)
        emit_history_debug(
            logger,
            "segment_view.poll.started",
            interval_ms=self._DEBUG_POLL_INTERVAL_MS,
            started=bool(timer_started),
        )
        self._record_poll_snapshot("initial")

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
        emit_history_debug(
            logger,
            "segment_view.schedule_render.request",
            conversation_id=conversation_id,
            pending_timeline=pending_timeline_id,
            entry_count=len(entry_ids) if entry_ids else 0,
            force=force,
            already_scheduled=self._pending_scheduled,
        )
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
            emit_history_debug(
                logger,
                "segment_view.schedule_render.dispatch",
                conversation_id=conversation_id,
                pending_timeline=pending_timeline_id,
                entry_count=len(entry_ids) if entry_ids else 0,
                force=force,
            )
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
        debug_start_ns = (
            time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        )
        self._pending_scheduled = False
        timeline = self._pending_timeline
        entry_ids = list(self._pending_entry_ids)
        force = self._pending_force
        self._pending_entry_ids.clear()
        self._pending_force = False

        emit_history_debug(
            logger,
            "segment_view.flush.prepared",
            pending_timeline=getattr(timeline, "conversation_id", None),
            entry_count=len(entry_ids),
            force=force,
        )

        conversation = self._callbacks.get_conversation()
        conversation_id = conversation.conversation_id if conversation else None
        emit_history_debug(
            logger,
            "segment_view.flush.context",
            conversation_id=conversation_id,
            pending_timeline=getattr(timeline, "conversation_id", None),
            pending_entries=len(getattr(timeline, "entries", ())),
        )
        if conversation is None:
            timeline = None
            emit_history_debug(
                logger,
                "segment_view.flush.timeline_skipped",
                conversation_id=conversation_id,
                reason="no_conversation",
            )
        elif timeline is None or timeline.conversation_id != conversation.conversation_id:
            build_start_ns = (
                time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
            )
            timeline = build_conversation_timeline(conversation)
            emit_history_debug(
                logger,
                "segment_view.flush.timeline_rebuilt",
                conversation_id=conversation_id,
                entry_count=len(getattr(timeline, "entries", ())),
                elapsed_ns=elapsed_ns(build_start_ns),
            )
        else:
            emit_history_debug(
                logger,
                "segment_view.flush.timeline_reused",
                conversation_id=conversation_id,
                entry_count=len(getattr(timeline, "entries", ())),
            )

        emit_history_debug(
            logger,
            "segment_view.flush.start",
            conversation_id=conversation_id,
            timeline_id=getattr(timeline, "conversation_id", None),
            entry_count=len(entry_ids),
            force=force,
        )

        self._apply_timeline(conversation, timeline, entry_ids, force)

        emit_history_debug(
            logger,
            "segment_view.flush.completed",
            conversation_id=conversation_id,
            timeline_id=getattr(timeline, "conversation_id", None),
            entry_count=len(entry_ids),
            force=force,
            elapsed_ns=elapsed_ns(debug_start_ns),
        )

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
        emit_history_debug(
            logger,
            "segment_view.apply_timeline.start",
            conversation_id=conversation_id,
            timeline_id=getattr(timeline, "conversation_id", None),
            entry_count=len(entry_ids),
            force=force,
        )

        if conversation is None or timeline is None:
            self._pending_timeline = None
            self._detach_active_conversation()
            self._show_start_placeholder()
            emit_history_debug(
                logger,
                "segment_view.apply_timeline.placeholder",
                conversation_id=conversation_id,
            )
        elif not timeline.entries:
            self._pending_timeline = timeline
            self._show_empty_conversation(conversation)
            emit_history_debug(
                logger,
                "segment_view.apply_timeline.empty",
                conversation_id=conversation_id,
            )
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
            emit_history_debug(
                logger,
                "segment_view.apply_timeline.entries",
                conversation_id=conversation_id,
                entry_count=len(timeline.entries),
                refreshed_ids=list(entry_ids) if entry_ids else None,
                force=force,
            )

        layout_start_ns = (
            time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        )
        panel.Layout()
        panel.FitInside()
        panel.SetupScrolling(scroll_x=False, scroll_y=True)
        layout_elapsed = elapsed_ns(layout_start_ns)
        scroll_requested = bool(last_card)
        if last_card is not None:
            self._scroll_to_bottom(last_card)
        copy_start_ns = (
            time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        )
        self._callbacks.update_copy_buttons(has_entries)
        copy_elapsed = elapsed_ns(copy_start_ns)
        header_start_ns = (
            time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        )
        self._callbacks.update_header()
        header_elapsed = elapsed_ns(header_start_ns)
        emit_history_debug(
            logger,
            "segment_view.apply_timeline.layout",
            conversation_id=conversation_id,
            layout_ns=layout_elapsed,
            copy_buttons_ns=copy_elapsed,
            header_ns=header_elapsed,
            scroll_requested=scroll_requested,
        )
        emit_history_debug(
            logger,
            "segment_view.apply_timeline.completed",
            conversation_id=conversation_id,
            has_entries=has_entries,
        )
        self._last_render_completed_ns = time.perf_counter_ns()
        self._record_poll_snapshot("apply_timeline")

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
            emit_history_debug(
                logger,
                "segment_view.update_cards.rebuild",
                conversation_id=conversation_id,
                previous_order=len(cache.order),
                desired_order=len(desired_order),
                force=force,
            )
            return self._render_full_conversation(conversation, timeline, cache)

        if not entry_ids:
            emit_history_debug(
                logger,
                "segment_view.update_cards.noop",
                conversation_id=conversation_id,
            )
            return None

        entry_lookup = {entry.entry_id: entry for entry in timeline.entries}
        last_card: wx.Window | None = None
        updated = 0

        for entry_id in entry_ids:
            timeline_entry = entry_lookup.get(entry_id)
            if timeline_entry is None:
                emit_history_debug(
                    logger,
                    "segment_view.update_cards.fallback",
                    conversation_id=conversation_id,
                    entry_id=entry_id,
                    reason="missing_timeline_entry",
                )
                return self._render_full_conversation(conversation, timeline, cache)
            card = cache.cards_by_entry.get(entry_id)
            if card is None or not self._is_window_alive(card):
                emit_history_debug(
                    logger,
                    "segment_view.update_cards.fallback",
                    conversation_id=conversation_id,
                    entry_id=entry_id,
                    reason="missing_card",
                )
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

        emit_history_debug(
            logger,
            "segment_view.update_cards.incremental",
            conversation_id=conversation_id,
            requested=len(entry_ids),
            updated=updated,
        )

        return last_card

    # ------------------------------------------------------------------
    def _render_full_conversation(
        self,
        conversation: ChatConversation,
        timeline: ConversationTimeline,
        cache: _ConversationRenderCache,
    ) -> wx.Window | None:
        conversation_id = conversation.conversation_id
        debug_start_ns = (
            time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        )
        panel = self._panel
        emit_history_debug(
            logger,
            "segment_view.render_full.start",
            conversation_id=conversation_id,
            entry_count=len(timeline.entries),
        )
        panel.Freeze()
        try:
            ordered_cards: list[tuple[str, TurnCard]] = []
            new_cards = 0
            reused_cards = 0
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
                    new_cards += 1
                else:
                    reused_cards += 1
                segments = build_entry_segments(entry)
                regenerate_callback = self._build_regenerate_callback(
                    timeline.conversation_id, entry
                )
                card.update(
                    segments=segments,
                    on_regenerate=regenerate_callback,
                    regenerate_enabled=not self._callbacks.is_running(),
                )
                cache.entry_snapshots[entry_id] = entry
                ordered_cards.append((entry_id, card))

            keep = {key for key, _ in ordered_cards}
            removed_cards = 0
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

            cache.order = [key for key, _ in ordered_cards]
            cache.entry_snapshots = {entry.entry_id: entry for entry in timeline.entries}
            cards = [card for _, card in ordered_cards]
            attach_start_ns = (
                time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
            )
            self._attach_cards_in_order(cards)
            emit_history_debug(
                logger,
                "segment_view.render_full.cards",
                conversation_id=conversation_id,
                entry_count=len(cards),
                new_cards=new_cards,
                reused_cards=reused_cards,
                removed_cards=removed_cards,
                attach_ns=elapsed_ns(attach_start_ns),
            )
            return cards[-1] if cards else None
        finally:
            panel.Thaw()
            emit_history_debug(
                logger,
                "segment_view.render_full.completed",
                conversation_id=conversation_id,
                entry_count=len(timeline.entries),
                elapsed_ns=elapsed_ns(debug_start_ns),
            )

    # ------------------------------------------------------------------
    def _attach_cards_in_order(self, cards: Sequence[TurnCard]) -> None:
        existing_children = [child.GetWindow() for child in self._sizer.GetChildren()]
        moved = 0
        attached = 0
        debug_start_ns = (
            time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        )
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
        emit_history_debug(
            logger,
            "segment_view.attach_cards.completed",
            attached=attached,
            moved=moved,
            kept=len(cards) - attached,
            elapsed_ns=elapsed_ns(debug_start_ns),
        )

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
        target_id = getattr(target, "_entry_id", None)
        emit_history_debug(
            logger,
            "segment_view.scroll.request",
            target_id=target_id,
            target_alive=self._is_window_alive(target),
        )
        sync_start_ns = (
            time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        )
        self._apply_scroll(target, "immediate")
        emit_history_debug(
            logger,
            "segment_view.scroll.request.completed",
            target_id=target_id,
            elapsed_ns=elapsed_ns(sync_start_ns),
        )
        wx.CallAfter(self._apply_scroll, target, "async")

    # ------------------------------------------------------------------
    def _apply_scroll(self, target: wx.Window | None, source: str = "immediate") -> None:
        panel = self._panel
        if not self._is_window_alive(panel):
            emit_history_debug(
                logger,
                "segment_view.scroll.apply.skipped",
                source=source,
                reason="panel_missing",
            )
            return
        debug_start_ns = (
            time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        )
        layout_start_ns = (
            time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        )
        panel.Layout()
        panel.FitInside()
        layout_elapsed = elapsed_ns(layout_start_ns)
        window: wx.Window | None = target if self._is_window_alive(target) else None
        if window is not None and window.GetParent() is not panel:
            window = None
        scrolled = False
        mode = "none"
        if window is not None:
            try:
                panel.ScrollChildIntoView(window)
            except RuntimeError:
                window = None
                mode = "runtime_error"
            else:
                scrolled = True
                mode = "target"
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
                    mode = "target_adjusted"
        if window is None:
            panel.ScrollChildIntoView(panel)
            scrolled = True
            if mode == "none":
                mode = "panel"
        emit_history_debug(
            logger,
            "segment_view.scroll.apply.completed",
            source=source,
            target_alive=self._is_window_alive(target),
            effective_window=bool(window),
            scrolled=scrolled,
            mode=mode,
            layout_ns=layout_elapsed,
            elapsed_ns=elapsed_ns(debug_start_ns),
        )

    # ------------------------------------------------------------------
    def _on_pane_toggled(self, _event: wx.CollapsiblePaneEvent) -> None:
        panel = self._panel
        if self._is_window_alive(panel):
            panel.Layout()
            panel.FitInside()

    # ------------------------------------------------------------------
    def _on_debug_poll_timer(self, event: wx.TimerEvent) -> None:
        if event.GetTimer() is not self._debug_poll_timer:
            event.Skip()
            return
        self._record_poll_snapshot("wx_timer")

    # ------------------------------------------------------------------
    def _collect_render_snapshot(self) -> dict[str, object]:
        panel = self._panel
        if not self._is_window_alive(panel):
            return {
                "panel_alive": False,
                "timer_running": self._debug_poll_timer.IsRunning(),
            }

        conversation = self._callbacks.get_conversation()
        conversation_id = conversation.conversation_id if conversation else None
        active_id = self._active_conversation_id
        cache = self._conversation_cache.get(active_id) if active_id else None
        card_count = len(cache.order) if cache else 0
        cached_snapshots = len(cache.entry_snapshots) if cache else 0
        pending_timeline_id = getattr(self._pending_timeline, "conversation_id", None)
        sizer_children = list(self._sizer.GetChildren())
        window_children = 0
        alive_children = 0
        for child in sizer_children:
            if not child.IsWindow():
                continue
            window_children += 1
            window = child.GetWindow()
            if self._is_window_alive(window):
                alive_children += 1
        previous_conversation_id = self._last_poll_conversation_id
        if previous_conversation_id == conversation_id:
            card_delta = card_count - self._last_poll_card_count
        else:
            card_delta = None
        snapshot = {
            "panel_alive": True,
            "conversation_id": conversation_id,
            "active_conversation_id": active_id,
            "card_count": card_count,
            "card_delta": card_delta,
            "cached_snapshots": cached_snapshots,
            "sizer_windows": window_children,
            "sizer_windows_alive": alive_children,
            "pending_entries": len(self._pending_entry_ids),
            "pending_timeline": pending_timeline_id,
            "pending_force": self._pending_force,
            "pending_scheduled": self._pending_scheduled,
            "panel_frozen": getattr(panel, "IsFrozen", lambda: False)(),
            "panel_enabled": panel.IsEnabled(),
            "panel_shown": panel.IsShown(),
            "timer_running": self._debug_poll_timer.IsRunning(),
            "elapsed_since_render_ns": elapsed_ns(self._last_render_completed_ns),
            "placeholders": {
                "current": self._is_window_alive(self._current_placeholder),
                "start": self._is_window_alive(self._start_placeholder),
            },
        }
        if cache is not None:
            snapshot["cache_order_size"] = len(cache.order)
        return snapshot

    def _record_poll_snapshot(self, source: str) -> None:
        monitor = getattr(self, "_poll_monitor", None)
        if monitor is None:
            return
        snapshot = self._collect_render_snapshot()
        snapshot["poll_source"] = source
        self._poll_sequence += 1
        snapshot["poll_sequence"] = self._poll_sequence
        monitor.update(snapshot, source)
        conversation_id = snapshot.get("conversation_id")
        card_count = snapshot.get("card_count")
        if isinstance(card_count, int):
            self._last_poll_card_count = card_count
        elif conversation_id != self._last_poll_conversation_id:
            self._last_poll_card_count = 0
        self._last_poll_conversation_id = conversation_id

    # ------------------------------------------------------------------
    def _on_panel_destroy(self, event: wx.WindowDestroyEvent) -> None:
        if event.GetEventObject() is self._panel:
            if self._debug_poll_timer.IsRunning():
                self._debug_poll_timer.Stop()
                emit_history_debug(
                    logger,
                    "segment_view.poll.stopped",
                    interval_ms=self._DEBUG_POLL_INTERVAL_MS,
                )
            monitor = getattr(self, "_poll_monitor", None)
            if monitor is not None:
                monitor.stop()
                self._poll_monitor = None
        event.Skip()

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
