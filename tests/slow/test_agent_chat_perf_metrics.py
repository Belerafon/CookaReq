"""Performance regression checks for the agent chat transcript rendering."""

from __future__ import annotations

import time
from contextlib import suppress

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.slow]


def test_transcript_rerender_is_fast(record_property) -> None:
    """Ensure that rerendering a large transcript stays within a time budget."""

    wx = pytest.importorskip("wx")
    from wx.lib.scrolledpanel import ScrolledPanel  # type: ignore[attr-defined]

    from app.application import ApplicationContext
    from app.ui.agent_chat_panel.segment_view import (  # noqa: WPS433 - test import
        SegmentListView,
        SegmentViewCallbacks,
    )
    from app.ui.agent_chat_panel.view_model import ConversationTimelineCache
    from app.ui.chat_entry import ChatConversation, ChatEntry

    context = ApplicationContext.for_gui()
    frame = wx.Frame(None)
    panel = wx.Panel(frame)
    scrolled = ScrolledPanel(panel)
    view_sizer = wx.BoxSizer(wx.VERTICAL)
    scrolled.SetSizer(view_sizer)
    scrolled.SetupScrolling()

    conversation = ChatConversation.new()
    entries: list[ChatEntry] = []
    for index in range(32):
        prompt_time = f"2025-01-01T00:{index:02d}:00+00:00"
        response_time = f"2025-01-01T00:{index:02d}:30+00:00"
        entries.append(
            ChatEntry(
                prompt=f"Prompt {index}",
                response=f"Response {index}",
                tokens=0,
                prompt_at=prompt_time,
                response_at=response_time,
            )
        )
    conversation.replace_entries(entries)

    timeline_cache = ConversationTimelineCache()
    timeline = timeline_cache.timeline_for(conversation)

    callbacks = SegmentViewCallbacks(
        get_conversation=lambda: conversation,
        is_running=lambda: False,
        on_regenerate=lambda *_args: None,
        update_copy_buttons=lambda _enabled: None,
        update_header=lambda: None,
    )

    view = SegmentListView(panel, scrolled, view_sizer, callbacks=callbacks)

    try:
        start = time.perf_counter()
        view.render_now(conversation=conversation, timeline=timeline, force=True)
        initial_duration = time.perf_counter() - start

        for _ in range(3):
            wx.YieldIfNeeded()

        rerender_start = time.perf_counter()
        view.render_now(
            conversation=conversation,
            timeline=timeline_cache.timeline_for(conversation),
            updated_entries=[entry.entry_id for entry in timeline.entries],
            force=False,
        )
        rerender_duration = time.perf_counter() - rerender_start

        record_property("transcript_initial_ms", initial_duration * 1000)
        record_property("transcript_rerender_ms", rerender_duration * 1000)

        assert rerender_duration < 0.35, "Transcript rerender took too long"
        assert rerender_duration < initial_duration
    finally:
        with suppress(Exception):
            frame.Destroy()
        context.close()

