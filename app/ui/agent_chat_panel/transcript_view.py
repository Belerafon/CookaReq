"""Transcript rendering helpers for the agent chat panel."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import wx
from wx.lib.scrolledpanel import ScrolledPanel

from ...i18n import _
from ..chat_entry import ChatConversation, ChatEntry
from ..helpers import dip
from ..widgets.chat_message import TranscriptMessagePanel
from .time_formatting import format_entry_timestamp
from .tool_summaries import summarize_tool_results

from typing import Any, Iterable


class TranscriptCallbacks:
    """Lightweight callback container used by :class:`TranscriptView`."""

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
    panels_by_entry: dict[int, TranscriptMessagePanel] = field(default_factory=dict)
    order: list[int] = field(default_factory=list)
    placeholder: wx.Window | None = None


class TranscriptView:
    """Manage rendering the transcript inside the chat panel."""

    def __init__(
        self,
        owner: wx.Window,
        panel: ScrolledPanel,
        sizer: wx.BoxSizer,
        *,
        callbacks: TranscriptCallbacks,
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
        last_panel: wx.Window | None = None
        has_entries = False
        transcript_panel = self._panel
        transcript_panel.Freeze()
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
                last_panel = self._display_conversation(conversation)
        finally:
            try:
                transcript_panel.Layout()
                transcript_panel.FitInside()
                transcript_panel.SetupScrolling(scroll_x=False, scroll_y=True)
            finally:
                transcript_panel.Thaw()
            if last_panel is not None:
                self._scroll_to_bottom(last_panel)
        self._callbacks.update_copy_buttons(has_entries)
        self._callbacks.update_header()

    # ------------------------------------------------------------------
    def forget_conversations(self, conversation_ids: Iterable[str]) -> None:
        for conversation_id in list(conversation_ids):
            cache = self._conversation_cache.pop(conversation_id, None)
            if cache is None:
                continue
            for panel in cache.panels_by_entry.values():
                if self._is_window_alive(panel):
                    if panel.GetContainingSizer() is self._sizer:
                        self._sizer.Detach(panel)
                    panel.Destroy()
            cache.panels_by_entry.clear()
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
    def _get_cache(self, conversation_id: str) -> _ConversationRenderCache:
        return self._conversation_cache.setdefault(
            conversation_id, _ConversationRenderCache()
        )

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
        self._sizer.Add(
            placeholder,
            0,
            wx.ALL,
            dip(self._owner, 8),
        )
        placeholder.Show()

    # ------------------------------------------------------------------
    def _show_empty_conversation(self, conversation: ChatConversation) -> None:
        self._detach_active_conversation()
        self._clear_current_placeholder()
        conversation_id = conversation.conversation_id
        cache = self._get_cache(conversation_id)
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
        self._sizer.Add(
            placeholder,
            0,
            wx.ALL,
            dip(self._owner, 8),
        )
        placeholder.Show()

    # ------------------------------------------------------------------
    def _display_conversation(
        self,
        conversation: ChatConversation,
    ) -> wx.Window | None:
        conversation_id = conversation.conversation_id
        cache = self._get_cache(conversation_id)
        self._active_conversation_id = conversation_id
        ordered: list[tuple[int, TranscriptMessagePanel]] = []
        for entry in conversation.entries:
            key = id(entry)
            panel = cache.panels_by_entry.get(key)
            data = self._prepare_entry_render_data(conversation, entry)
            if panel is None or not self._is_window_alive(panel):
                panel = self._create_entry_panel(entry, data)
                cache.panels_by_entry[key] = panel
            else:
                self._update_entry_panel(panel, data)
            ordered.append((key, panel))
        keep_keys = {key for key, _ in ordered}
        for stale_key in list(cache.panels_by_entry.keys()):
            if stale_key in keep_keys:
                continue
            panel = cache.panels_by_entry.pop(stale_key)
            if self._is_window_alive(panel):
                if panel.GetContainingSizer() is self._sizer:
                    self._sizer.Detach(panel)
                panel.Destroy()
        cache.order = [key for key, _ in ordered]
        panels = [panel for _, panel in ordered]
        self._attach_panels_in_order(panels)
        return panels[-1] if panels else None

    # ------------------------------------------------------------------
    def _attach_panels_in_order(
        self, panels: Sequence[TranscriptMessagePanel]
    ) -> None:
        existing_children = [child.GetWindow() for child in self._sizer.GetChildren()]
        for index, panel in enumerate(panels):
            if panel.GetContainingSizer() is self._sizer:
                try:
                    current_index = existing_children.index(panel)
                except ValueError:
                    current_index = -1
                if current_index != index:
                    self._sizer.Detach(panel)
                    self._sizer.Insert(index, panel, 0, wx.EXPAND)
            else:
                self._sizer.Insert(index, panel, 0, wx.EXPAND)
            panel.Show()
        keep = set(panels)
        for child in list(self._sizer.GetChildren()):
            window = child.GetWindow()
            if window is None or window in keep:
                continue
            self._sizer.Detach(window)
            if self._is_window_alive(window):
                window.Hide()

    # ------------------------------------------------------------------
    def _prepare_entry_render_data(
        self, conversation: ChatConversation, entry: ChatEntry
    ) -> dict[str, Any]:
        response_source = entry.display_response or entry.response
        tool_summaries = summarize_tool_results(entry.tool_results)
        valid_hint_keys = {"user", "agent"}
        for summary in tool_summaries:
            valid_hint_keys.add(TranscriptMessagePanel.tool_layout_hint_key(summary))
        hints = entry.layout_hints if isinstance(entry.layout_hints, dict) else {}
        sanitized: dict[str, int] = {}
        for key, value in hints.items():
            if key not in valid_hint_keys:
                continue
            try:
                width = int(value)
            except (TypeError, ValueError):
                continue
            if width <= 0:
                continue
            sanitized[str(key)] = width
        entry.layout_hints = sanitized
        can_regenerate = (
            entry is conversation.entries[-1]
            and entry.response_at is not None
        )
        on_regenerate: Callable[[], None] | None = None
        if can_regenerate:
            conversation_id = conversation.conversation_id

            def callback(entry_ref: ChatEntry = entry) -> None:
                self._callbacks.on_regenerate(conversation_id, entry_ref)

            on_regenerate = callback
        return {
            "prompt": entry.prompt,
            "response": response_source or entry.response,
            "prompt_timestamp": format_entry_timestamp(entry.prompt_at),
            "response_timestamp": format_entry_timestamp(entry.response_at),
            "on_regenerate": on_regenerate,
            "regenerate_enabled": not self._callbacks.is_running(),
            "tool_summaries": tool_summaries,
            "context_messages": entry.context_messages,
            "reasoning_segments": entry.reasoning,
            "regenerated": getattr(entry, "regenerated", False),
            "layout_hints": entry.layout_hints,
        }

    # ------------------------------------------------------------------
    def _create_entry_panel(
        self,
        entry: ChatEntry,
        data: dict[str, Any],
    ) -> TranscriptMessagePanel:
        panel = TranscriptMessagePanel(
            self._panel,
            prompt=data["prompt"],
            response=data["response"],
            prompt_timestamp=data["prompt_timestamp"],
            response_timestamp=data["response_timestamp"],
            on_regenerate=data["on_regenerate"],
            regenerate_enabled=data["regenerate_enabled"],
            tool_summaries=data["tool_summaries"],
            context_messages=data["context_messages"],
            reasoning_segments=data["reasoning_segments"],
            regenerated=data["regenerated"],
            layout_hints=data["layout_hints"],
            on_layout_hint=lambda key, width, entry_ref=entry: entry_ref.layout_hints.__setitem__(
                key, int(width)
            ),
        )
        panel.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self._on_pane_toggled)
        return panel

    # ------------------------------------------------------------------
    def _update_entry_panel(
        self,
        panel: TranscriptMessagePanel,
        data: dict[str, Any],
    ) -> None:
        panel.update_from_entry(
            prompt=data["prompt"],
            response=data["response"],
            prompt_timestamp=data["prompt_timestamp"],
            response_timestamp=data["response_timestamp"],
            on_regenerate=data["on_regenerate"],
            regenerate_enabled=data["regenerate_enabled"],
            tool_summaries=data["tool_summaries"],
            context_messages=data["context_messages"],
            reasoning_segments=data["reasoning_segments"],
            regenerated=data["regenerated"],
            layout_hints=data["layout_hints"],
        )

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
        except RuntimeError:  # pragma: no cover - defensive cleanup
            pass
        if placeholder is self._start_placeholder:
            self._start_placeholder = None
        for cache in self._conversation_cache.values():
            if cache.placeholder is placeholder:
                cache.placeholder = None
        self._current_placeholder = None

    # ------------------------------------------------------------------
    def _detach_active_conversation(self) -> None:
        conversation_id = self._active_conversation_id
        if conversation_id is None:
            return
        cache = self._conversation_cache.get(conversation_id)
        if cache is not None:
            for panel in cache.panels_by_entry.values():
                if not self._is_window_alive(panel):
                    continue
                if panel.GetContainingSizer() is self._sizer:
                    self._sizer.Detach(panel)
                panel.Hide()
            placeholder = cache.placeholder
            if self._is_window_alive(placeholder):
                if placeholder.GetContainingSizer() is self._sizer:
                    self._sizer.Detach(placeholder)
                placeholder.Hide()
        self._active_conversation_id = None
        self._clear_current_placeholder()

    # ------------------------------------------------------------------
    def _scroll_to_bottom(self, target: wx.Window | None) -> None:
        self._apply_scroll(target)
        wx.CallAfter(self._apply_scroll, target)

    # ------------------------------------------------------------------
    def _apply_scroll(self, target: wx.Window | None) -> None:
        panel = self._panel
        if not self._is_window_alive(panel):
            return
        window: wx.Window | None = target if self._is_window_alive(target) else None
        if window is not None and window.GetParent() is not panel:
            window = None
        if window is not None:
            try:
                panel.ScrollChildIntoView(window)
            except RuntimeError:
                window = None
        bottom_pos = max(0, panel.GetScrollRange(wx.VERTICAL))
        view_x, view_y = panel.GetViewStart()
        if bottom_pos != view_y:
            panel.Scroll(view_x, bottom_pos)

    # ------------------------------------------------------------------
    @staticmethod
    def _is_window_alive(window: wx.Window | None) -> bool:
        if window is None:
            return False
        try:
            return bool(window) and not window.IsBeingDeleted()
        except RuntimeError:
            return False

    # ------------------------------------------------------------------
    def _on_pane_toggled(self, event: wx.CollapsiblePaneEvent) -> None:
        event.Skip()
        panel = self._panel
        panel.Layout()
        panel.FitInside()
        panel.SetupScrolling(scroll_x=False, scroll_y=True)
        window = event.GetEventObject()
        if isinstance(window, wx.Window):
            panel.ScrollChildIntoView(window)


__all__ = ["TranscriptView", "TranscriptCallbacks"]
