"""Performance benchmarks for the agent chat GUI widgets."""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

import pytest

from app.llm.tokenizer import TokenCountResult
from app.ui.chat_entry import ChatConversation, ChatEntry

from tests.gui.test_agent_chat_panel import create_panel, destroy_panel, flush_wx_events


pytestmark = [pytest.mark.gui, pytest.mark.gui_full]


@dataclass(slots=True)
class ConversationSpec:
    """Describe a synthetic conversation for the benchmark."""

    prompts: int
    prompt_length: int
    response_length: int


def _create_entry(prompt: str, response: str) -> ChatEntry:
    """Return a chat entry without triggering expensive tokenisation."""

    token_info = TokenCountResult.exact(  # small placeholder value suffices
        max(len(prompt), len(response)) // 4 or 1,
        model="benchmark",
    )
    return ChatEntry(
        prompt=prompt,
        response=response,
        tokens=token_info.tokens or 0,
        token_info=token_info,
        prompt_at="2024-01-01T00:00:00Z",
        response_at="2024-01-01T00:00:05Z",
    )


def _create_conversation(spec: ConversationSpec, *, index: int) -> ChatConversation:
    conversation = ChatConversation.new()
    conversation.title = f"Conversation {index}"
    conversation.entries.clear()
    for entry_index in range(spec.prompts):
        prompt = f"Prompt {entry_index}: " + ("Plan release " * spec.prompt_length).strip()
        response = f"Response {entry_index}: " + (
            "Detailed answer " * spec.response_length
        ).strip()
        conversation.entries.append(_create_entry(prompt, response))
    if conversation.entries:
        conversation.updated_at = conversation.entries[-1].response_at or conversation.updated_at
    return conversation


def _prepare_panel_history(panel, conversations: list[ChatConversation]) -> None:
    panel.conversations.clear()
    panel.conversations.extend(conversations)
    active_id = conversations[0].conversation_id if conversations else None
    panel._set_active_conversation_id(active_id)
    panel._notify_history_changed()
    panel._refresh_history_list()
    panel._render_transcript()


def _switch(panel, wx_app, wx, indices: list[int]) -> list[float]:
    durations: list[float] = []
    for index in indices:
        start = time.perf_counter()
        panel._activate_conversation_by_index(index)
        wx_app.Yield()
        flush_wx_events(wx)
        durations.append(time.perf_counter() - start)
    return durations


def test_transcript_switch_benchmark(tmp_path, wx_app, record_property):
    """Measure conversation switch latency with a populated transcript."""

    class IdleAgent:
        def run_command(self, *args, **kwargs):  # pragma: no cover - interface stub
            raise AssertionError("Agent commands are not expected during the benchmark")

    wx, frame, panel = create_panel(tmp_path, wx_app, IdleAgent())

    try:
        spec = ConversationSpec(prompts=18, prompt_length=3, response_length=12)
        conversations = [_create_conversation(spec, index=i) for i in range(6)]
        _prepare_panel_history(panel, conversations)
        flush_wx_events(wx)

        indices = [1, 0, 2, 0, 3, 0, 4, 0, 5, 0]
        warmup = _switch(panel, wx_app, wx, indices)
        measurement = _switch(panel, wx_app, wx, indices)

        warmup_ms = [round(d * 1000, 3) for d in warmup]
        measurement_ms = [round(d * 1000, 3) for d in measurement]
        stats = {
            "min_ms": round(min(measurement) * 1000, 3),
            "median_ms": round(statistics.median(measurement) * 1000, 3),
            "max_ms": round(max(measurement) * 1000, 3),
        }

        record_property("agent_chat_switch_warmup_ms", warmup_ms)
        record_property("agent_chat_switch_measure_ms", measurement_ms)
        record_property("agent_chat_switch_stats", stats)
        print("AGENT_CHAT_SWITCH_WARMUP_MS", warmup_ms)
        print("AGENT_CHAT_SWITCH_MEASURE_MS", measurement_ms)
        print("AGENT_CHAT_SWITCH_STATS", stats)

        assert max(measurement) < 0.75, "Switching chats exceeds the acceptable latency"
    finally:
        destroy_panel(frame, panel)
