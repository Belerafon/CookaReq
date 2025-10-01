"""Tests for the agent chat transcript view-model."""

from __future__ import annotations

from app.ui.agent_chat_panel.view_model import (
    ChatEventKind,
    build_conversation_timeline,
)
from app.ui.chat_entry import ChatConversation, ChatEntry


def _conversation_with_entry(entry: ChatEntry) -> ChatConversation:
    return ChatConversation(
        conversation_id="conv-1",
        title="Test",
        created_at="2025-09-30T20:50:00+00:00",
        updated_at="2025-09-30T20:50:00+00:00",
        entries=[entry],
    )


def test_build_conversation_timeline_compiles_events() -> None:
    entry = ChatEntry(
        prompt="Переведи требования",
        response="Готово",
        tokens=10,
        prompt_at="2025-09-30T20:50:10+00:00",
        response_at="2025-09-30T20:50:12+00:00",
        context_messages=(
            {"role": "system", "content": "Поддерживай MCP"},
        ),
        reasoning=(
            {"type": "thought", "text": "Нужно пройтись по каждому требованию"},
        ),
        tool_results=(
            {
                "tool_name": "get_requirement",
                "started_at": "2025-09-30T20:50:10+00:00",
                "completed_at": "2025-09-30T20:50:11+00:00",
                "tool_call_id": "tool-1",
            },
        ),
        raw_result={"answer": "Готово"},
        layout_hints={"user": "140", "agent": 220, "invalid": 0},
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)

    assert timeline.conversation_id == "conv-1"
    assert len(timeline.entries) == 1
    entry_timeline = timeline.entries[0]
    assert entry_timeline.entry_id == "conv-1:0"
    assert entry_timeline.prompt.kind is ChatEventKind.PROMPT
    assert entry_timeline.prompt.text == "Переведи требования"
    assert entry_timeline.context is not None
    assert entry_timeline.context.messages[0]["role"] == "system"
    assert entry_timeline.reasoning is not None
    assert entry_timeline.reasoning.segments[0]["type"] == "thought"
    assert entry_timeline.response is not None
    assert entry_timeline.response.text == "Готово"
    assert entry_timeline.response.formatted_timestamp.endswith("20:50:12")
    assert entry_timeline.tool_calls
    tool_event = entry_timeline.tool_calls[0]
    assert tool_event.summary.index == 1
    assert tool_event.call_identifier == "tool-1"
    assert tool_event.raw_payload["tool_name"] == "get_requirement"
    assert entry_timeline.raw_payload is not None
    assert entry_timeline.raw_payload.payload["answer"] == "Готово"
    assert entry_timeline.layout_hints == {"user": 140, "agent": 220}
    assert entry_timeline.can_regenerate is True

    kinds = [event.kind for event in timeline.events]
    assert kinds == [
        ChatEventKind.PROMPT,
        ChatEventKind.CONTEXT,
        ChatEventKind.REASONING,
        ChatEventKind.RESPONSE,
        ChatEventKind.TOOL_CALL,
        ChatEventKind.RAW_PAYLOAD,
    ]


def test_tool_call_events_sorted_by_timestamp() -> None:
    entry = ChatEntry(
        prompt="",
        response="",
        tokens=1,
        prompt_at="2025-09-30T20:50:10+00:00",
        response_at="2025-09-30T20:52:58+00:00",
        tool_results=(
            {
                "tool_name": "update_requirement_field",
                "agent_status": "failed",
                "started_at": "2025-09-30T20:52:57+00:00",
                "completed_at": "2025-09-30T20:52:58+00:00",
                "tool_call_id": "tool-6",
            },
            {
                "tool_name": "get_requirement",
                "started_at": "2025-09-30T20:50:10+00:00",
                "completed_at": "2025-09-30T20:50:11+00:00",
                "tool_call_id": "tool-1",
            },
            {
                "tool_name": "update_requirement_field",
                "agent_status": "failed",
                "started_at": "2025-09-30T20:52:05+00:00",
                "completed_at": "2025-09-30T20:52:05+00:00",
                "tool_call_id": "tool-4",
            },
        ),
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)

    entry_timeline = timeline.entries[0]
    tool_ids = [event.call_identifier for event in entry_timeline.tool_calls]
    assert tool_ids == ["tool-1", "tool-4", "tool-6"]
    assert [event.summary.index for event in entry_timeline.tool_calls] == [1, 2, 3]

    # tool events should appear before raw/system events when present
    kinds = [event.kind for event in entry_timeline.events]
    assert kinds[: len(tool_ids)] == [ChatEventKind.TOOL_CALL] * len(tool_ids)

    # chronological order is derived from timestamps
    timestamps = [event.timestamp for event in entry_timeline.tool_calls]
    assert timestamps == [
        "2025-09-30T20:50:10+00:00",
        "2025-09-30T20:52:05+00:00",
        "2025-09-30T20:52:57+00:00",
    ]
