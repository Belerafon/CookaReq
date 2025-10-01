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
    assert entry_timeline.entry is entry
    assert entry_timeline.prompt.kind is ChatEventKind.PROMPT
    assert entry_timeline.prompt.text == "Переведи требования"
    assert entry_timeline.context is not None
    assert entry_timeline.context.messages[0]["role"] == "system"
    assert entry_timeline.reasoning is not None
    assert entry_timeline.reasoning.segments[0]["type"] == "thought"
    assert entry_timeline.llm_request is not None
    assert entry_timeline.llm_request.messages
    assert entry_timeline.response is not None
    assert entry_timeline.response.text == "Готово"
    assert entry_timeline.response.formatted_timestamp.endswith("20:50:12")
    assert entry_timeline.tool_calls
    tool_event = entry_timeline.tool_calls[0]
    assert tool_event.summary.index == 1
    assert tool_event.call_identifier == "tool-1"
    assert tool_event.raw_payload["tool_name"] == "get_requirement"
    assert tool_event.summary.raw_payload == tool_event.raw_payload
    assert entry_timeline.raw_payload is not None
    assert entry_timeline.raw_payload.payload["answer"] == "Готово"
    assert entry_timeline.layout_hints == {"user": 140, "agent": 220}
    assert entry_timeline.can_regenerate is True

    kinds = [event.kind for event in timeline.events]
    assert kinds == [
        ChatEventKind.PROMPT,
        ChatEventKind.CONTEXT,
        ChatEventKind.LLM_REQUEST,
        ChatEventKind.REASONING,
        ChatEventKind.TOOL_CALL,
        ChatEventKind.RESPONSE,
        ChatEventKind.RAW_PAYLOAD,
    ]
    assert tool_event.llm_request is None


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

    kinds = [event.kind for event in entry_timeline.events]
    first_tool_index = kinds.index(ChatEventKind.TOOL_CALL)
    tool_slice = kinds[first_tool_index : first_tool_index + len(tool_ids)]
    assert tool_slice == [ChatEventKind.TOOL_CALL] * len(tool_ids)

    # chronological order is derived from timestamps
    timestamps = [event.timestamp for event in entry_timeline.tool_calls]
    assert timestamps == [
        "2025-09-30T20:50:10+00:00",
        "2025-09-30T20:52:05+00:00",
        "2025-09-30T20:52:57+00:00",
    ]


def test_tool_call_event_includes_llm_request_payload() -> None:
    entry = ChatEntry(
        prompt="",
        response="",
        tokens=1,
        prompt_at="2025-10-01T08:52:30+00:00",
        response_at="2025-10-01T08:52:40+00:00",
        tool_results=[
            {
                "tool_name": "update_requirement_field",
                "tool_call_id": "call-1",
                "started_at": "2025-10-01T08:52:35+00:00",
                "completed_at": "2025-10-01T08:52:39+00:00",
                "ok": False,
            }
        ],
        raw_result={
            "diagnostic": {
                "llm_steps": [
                    {
                        "step": 1,
                        "response": {
                            "content": "Applying updates",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "name": "update_requirement_field",
                                    "arguments": {
                                        "rid": "DEMO16",
                                        "field": "title",
                                        "value": "Новое название",
                                    },
                                }
                            ],
                        },
                    }
                ]
            }
        },
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)
    tool_event = timeline.entries[0].tool_calls[0]
    assert tool_event.llm_request is not None
    request_payload = tool_event.llm_request
    assert isinstance(request_payload, dict)
    assert "tool_call" in request_payload
    call_payload = request_payload["tool_call"]
    assert isinstance(call_payload, dict)
    assert call_payload.get("arguments", {}).get("rid") == "DEMO16"
    response_payload = request_payload.get("response")
    assert isinstance(response_payload, dict)
    assert response_payload.get("content") == "Applying updates"


def test_step_responses_rendered_as_events() -> None:
    entry = ChatEntry(
        prompt="do work",
        response="Final result",
        tokens=1,
        prompt_at="2025-10-01T08:00:00+00:00",
        response_at="2025-10-01T08:05:00+00:00",
        tool_results=[
            {
                "tool_name": "update_requirement_field",
                "tool_call_id": "call-1",
                "started_at": "2025-10-01T08:01:00+00:00",
                "completed_at": "2025-10-01T08:02:00+00:00",
                "ok": False,
            }
        ],
        raw_result={
            "diagnostic": {
                "llm_steps": [
                    {
                        "step": 1,
                        "response": {
                            "content": "Preparing request",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "name": "update_requirement_field",
                                    "arguments": {"rid": "REQ-1"},
                                }
                            ],
                        },
                    },
                    {
                        "step": 2,
                        "response": {
                            "content": "Final result",
                        },
                    },
                ]
            }
        },
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)
    entry_timeline = timeline.entries[0]

    assert entry_timeline.intermediate_responses
    step_event = entry_timeline.intermediate_responses[0]
    assert step_event.text == "Preparing request"
    assert step_event.step_index == 1
    assert step_event.is_final is False

    final_event = entry_timeline.response
    assert final_event is not None
    assert final_event.text == "Final result"
    assert final_event.is_final is True

    response_events = [
        event
        for event in entry_timeline.events
        if event.kind is ChatEventKind.RESPONSE
    ]
    assert len(response_events) == 2
    assert response_events[0] is step_event
    assert response_events[1] is final_event

    tool_index = entry_timeline.events.index(entry_timeline.tool_calls[0])
    assert entry_timeline.events.index(step_event) < tool_index < entry_timeline.events.index(
        final_event
    )


def test_tool_summary_compacts_error_details() -> None:
    entry = ChatEntry(
        prompt="",
        response="",
        tokens=1,
        prompt_at="2025-10-01T08:00:00+00:00",
        response_at="2025-10-01T08:05:00+00:00",
        tool_results=[
            {
                "tool_name": "update_requirement_field",
                "tool_call_id": "tool-1",
                "agent_status": "failed: update_requirement_field() missing rid",
                "started_at": "2025-10-01T08:01:00+00:00",
                "completed_at": "2025-10-01T08:01:05+00:00",
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "update_requirement_field() missing 1 required positional argument: 'rid'",
                },
            }
        ],
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)
    summary = timeline.entries[0].tool_calls[0].summary

    assert summary.status == "failed"
    assert any("Error VALIDATION_ERROR" in line for line in summary.bullet_lines)
    assert not any(line.startswith("Error message:") for line in summary.bullet_lines)


def test_llm_request_event_uses_diagnostic_sequence() -> None:
    entry = ChatEntry(
        prompt="translate",
        response="done",
        tokens=1,
        raw_result={
            "diagnostic": {
                "llm_request_messages_sequence": [
                    {
                        "step": 1,
                        "messages": [
                            {"role": "system", "content": "sys"},
                            {"role": "user", "content": "translate"},
                        ],
                    }
                ]
            }
        },
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)
    llm_event = timeline.entries[0].llm_request
    assert llm_event is not None
    assert llm_event.messages[0]["role"] == "system"
    assert llm_event.messages[-1]["content"] == "translate"
    assert llm_event.sequence is not None
    assert llm_event.sequence[0]["step"] == 1


def test_event_timestamps_fall_back_to_conversation_times() -> None:
    entry = ChatEntry(
        prompt="hello",
        response="",
        tokens=1,
        tool_results=[{"tool_name": "noop"}],
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)
    entry_timeline = timeline.entries[0]
    assert entry_timeline.prompt.timestamp == "2025-09-30T20:50:00+00:00"
    assert entry_timeline.response is None
    assert entry_timeline.llm_request is not None
    assert entry_timeline.llm_request.timestamp == "2025-09-30T20:50:00+00:00"
    tool_event = entry_timeline.tool_calls[0]
    assert tool_event.timestamp == "2025-09-30T20:50:00+00:00"
    raw_event = entry_timeline.raw_payload
    assert raw_event is None
