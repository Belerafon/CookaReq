"""Segment-oriented transcript rendering for the agent chat panel."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field

import wx
from wx.lib.scrolledpanel import ScrolledPanel

from ...i18n import _
from ..chat_entry import ChatConversation, ChatEntry
from ..helpers import dip
from .components.segments import TurnCard
from .view_model import AgentSegment, TranscriptSegment, build_transcript_segments


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
        self._owner = owner
        self._panel = panel
        self._sizer = sizer
        self._callbacks = callbacks
        self._conversation_cache: dict[str, _ConversationRenderCache] = {}
        self._active_conversation_id: str | None = None
        self._current_placeholder: wx.Window | None = None
        self._start_placeholder: wx.Window | None = None

    # ------------------------------------------------------------------
    def render(self) -> None:
        last_card: wx.Window | None = None
        has_entries = False
        container = self._panel
        container.Freeze()
        try:
            conversation = self._callbacks.get_conversation()
            if conversation is None:
                self._detach_active_conversation()
                self._show_start_placeholder()
            elif not conversation.entries:
                self._show_empty_conversation(conversation)
            else:
                has_entries = True
                if self._active_conversation_id != conversation.conversation_id:
                    self._detach_active_conversation()
                self._clear_current_placeholder()
                last_card = self._display_conversation(conversation)
        finally:
            try:
                container.Layout()
                container.FitInside()
                container.SetupScrolling(scroll_x=False, scroll_y=True)
            finally:
                container.Thaw()
            if last_card is not None:
                self._scroll_to_bottom(last_card)
        self._callbacks.update_copy_buttons(has_entries)
        self._callbacks.update_header()

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
    def _display_conversation(
        self, conversation: ChatConversation
    ) -> wx.Window | None:
        conversation_id = conversation.conversation_id
        cache = self._conversation_cache.setdefault(
            conversation_id, _ConversationRenderCache()
        )
        self._active_conversation_id = conversation_id

        segments = build_transcript_segments(conversation)
        grouped: dict[str, list[TranscriptSegment]] = defaultdict(list)
        for segment in segments.segments:
            grouped[segment.entry_id].append(segment)

        ordered_cards: list[tuple[str, TurnCard]] = []
        for entry_id in segments.entry_order:
            entry_segments = grouped.get(entry_id)
            if not entry_segments:
                continue
            card = cache.cards_by_entry.get(entry_id)
            entry_index = entry_segments[0].entry_index
            chat_entry = conversation.entries[entry_index]
            regenerate_callback: Callable[[], None] | None = None
            if any(
                seg.kind == "agent"
                and isinstance(seg.payload, AgentSegment)
                and seg.payload.can_regenerate
                for seg in entry_segments
            ):

                def _callback(entry_ref: ChatEntry = chat_entry) -> None:
                    self._callbacks.on_regenerate(conversation_id, entry_ref)

                regenerate_callback = _callback

            if card is None or not self._is_window_alive(card):
                card = TurnCard(
                    self._panel,
                    entry_id=entry_id,
                    entry_index=entry_index,
                    on_layout_hint=self._make_hint_recorder(chat_entry),
                )
                card.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self._on_pane_toggled)
                cache.cards_by_entry[entry_id] = card
            card.update(
                segments=entry_segments,
                on_regenerate=regenerate_callback,
                regenerate_enabled=not self._callbacks.is_running(),
            )
            ordered_cards.append((entry_id, card))

        keep = {key for key, _ in ordered_cards}
        for stale_key in list(cache.cards_by_entry.keys()):
            if stale_key in keep:
                continue
            card = cache.cards_by_entry.pop(stale_key)
            if self._is_window_alive(card):
                if card.GetContainingSizer() is self._sizer:
                    self._sizer.Detach(card)
                card.Destroy()

        cache.order = [key for key, _ in ordered_cards]
        cards = [card for _, card in ordered_cards]
        self._attach_cards_in_order(cards)
        return cards[-1] if cards else None

    # ------------------------------------------------------------------
    def _attach_cards_in_order(self, cards: Sequence[TurnCard]) -> None:
        existing_children = [child.GetWindow() for child in self._sizer.GetChildren()]
        for index, card in enumerate(cards):
            if card.GetContainingSizer() is self._sizer:
                try:
                    current_index = existing_children.index(card)
                except ValueError:
                    current_index = -1
                if current_index != index:
                    self._sizer.Detach(card)
                    self._sizer.Insert(index, card, 0, wx.EXPAND)
            else:
                self._sizer.Insert(index, card, 0, wx.EXPAND)
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


__all__ = ["SegmentViewCallbacks", "SegmentListView"]
