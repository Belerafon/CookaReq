"""Transcript rendering helpers for the agent chat panel."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import time

import wx
from wx.lib.scrolledpanel import ScrolledPanel

from ...i18n import _
from ..chat_entry import ChatConversation, ChatEntry
from ..helpers import dip
from ..widgets.chat_message import TranscriptMessagePanel
from .time_formatting import format_entry_timestamp
from .tool_summaries import summarize_tool_results

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .panel import _ChatSwitchDiagnostics


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

    # ------------------------------------------------------------------
    def render(self, *, diagnostics: "_ChatSwitchDiagnostics" | None = None) -> None:
        last_panel: wx.Window | None = None
        has_entries = False
        transcript_panel = self._panel
        transcript_panel.Freeze()

        def run(label: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            if diagnostics is not None:
                return diagnostics.step(label, func, *args, **kwargs)
            return func(*args, **kwargs)

        try:
            run("transcript:clear", self._sizer.Clear, delete_windows=True)
            conversation = run(
                "transcript:get_conversation", self._callbacks.get_conversation
            )
            if conversation is None:
                placeholder = run(
                    "transcript:placeholder:init",
                    wx.StaticText,
                    transcript_panel,
                    label=_("Start chatting with the agent to see responses here."),
                )
                run(
                    "transcript:placeholder:add",
                    self._sizer.Add,
                    placeholder,
                    0,
                    wx.ALL,
                    dip(self._owner, 8),
                )
            elif not conversation.entries:
                placeholder = run(
                    "transcript:placeholder:empty",
                    wx.StaticText,
                    transcript_panel,
                    label=_(
                        "This chat does not have any messages yet. Send one to get started."
                    ),
                )
                run(
                    "transcript:placeholder:add",
                    self._sizer.Add,
                    placeholder,
                    0,
                    wx.ALL,
                    dip(self._owner, 8),
                )
            else:
                has_entries = True
                last_entry = conversation.entries[-1]
                for index, entry in enumerate(conversation.entries):
                    entry_start = time.perf_counter()
                    can_regenerate = (
                        entry is last_entry and entry.response_at is not None
                    )
                    on_regenerate = (
                        lambda e=entry, cid=conversation.conversation_id: self._callbacks.on_regenerate(cid, e)
                    ) if can_regenerate else None
                    tool_summaries = summarize_tool_results(entry.tool_results)
                    response_text = entry.display_response or entry.response
                    valid_hint_keys = {"user", "agent"}
                    for summary in tool_summaries:
                        valid_hint_keys.add(
                            TranscriptMessagePanel.tool_layout_hint_key(summary)
                        )
                    hints = (
                        entry.layout_hints if isinstance(entry.layout_hints, dict) else {}
                    )
                    entry.layout_hints = {
                        key: value for key, value in hints.items() if key in valid_hint_keys
                    }
                    panel = TranscriptMessagePanel(
                        transcript_panel,
                        prompt=entry.prompt,
                        response=response_text,
                        prompt_timestamp=format_entry_timestamp(entry.prompt_at),
                        response_timestamp=format_entry_timestamp(entry.response_at),
                        on_regenerate=on_regenerate,
                        regenerate_enabled=not self._callbacks.is_running(),
                        tool_summaries=tool_summaries,
                        context_messages=entry.context_messages,
                        reasoning_segments=entry.reasoning,
                        regenerated=getattr(entry, "regenerated", False),
                        layout_hints=entry.layout_hints,
                        on_layout_hint=lambda key, width, entry=entry: entry.layout_hints.__setitem__(
                            key, int(width)
                        ),
                    )
                    panel.Bind(wx.EVT_COLLAPSIBLEPANE_CHANGED, self._on_pane_toggled)
                    self._sizer.Add(panel, 0, wx.EXPAND)
                    last_panel = panel
                    if diagnostics is not None:
                        prompt_len = len(entry.prompt or "")
                        response_source = entry.display_response or entry.response or ""
                        response_len = (
                            len(response_source)
                            if isinstance(response_source, str)
                            else 0
                        )
                        tool_results = entry.tool_results
                        if isinstance(tool_results, (str, bytes, bytearray)):
                            tool_count = 1 if tool_results else 0
                        elif isinstance(tool_results, Sequence):
                            tool_count = len(tool_results)
                        elif tool_results:
                            tool_count = 1
                        else:
                            tool_count = 0
                        duration = time.perf_counter() - entry_start
                        diagnostics.add_duration(
                            (
                                f"transcript:entry[{index}] "
                                f"prompt={prompt_len} "
                                f"response={response_len} "
                                f"tools={tool_count}"
                            ),
                            duration,
                        )
        finally:
            try:
                run("transcript:layout", transcript_panel.Layout)
                run("transcript:fit_inside", transcript_panel.FitInside)
                run(
                    "transcript:setup_scrolling",
                    transcript_panel.SetupScrolling,
                    scroll_x=False,
                    scroll_y=True,
                )
            finally:
                transcript_panel.Thaw()
            if last_panel is not None:
                run("transcript:scroll_bottom", self._scroll_to_bottom, last_panel)
        run(
            "transcript:update_copy_buttons",
            self._callbacks.update_copy_buttons,
            has_entries,
        )
        run("transcript:update_header", self._callbacks.update_header)

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
