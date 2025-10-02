from collections.abc import Mapping

import pytest

from app.ui.agent_chat_panel.view_model import build_conversation_timeline
from app.ui.chat_entry import ChatConversation, ChatEntry


def _conversation_with_entry(entry: ChatEntry) -> ChatConversation:
    return ChatConversation(
        conversation_id="conv-1",
        title="Test",
        created_at="2025-09-30T20:50:00+00:00",
        updated_at="2025-09-30T20:50:00+00:00",
        entries=[entry],
    )


def test_build_conversation_timeline_compiles_turn() -> None:
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
    assert entry_timeline.entry is entry
    assert entry_timeline.entry_id == "conv-1:0"
    assert entry_timeline.prompt is not None
    assert entry_timeline.prompt.text == "Переведи требования"
    assert entry_timeline.prompt.timestamp.raw == "2025-09-30T20:50:10+00:00"
    assert entry_timeline.context_messages
    assert entry_timeline.context_messages[0]["role"] == "system"

    turn = entry_timeline.agent_turn
    assert turn is not None
    assert turn.timestamp.raw == "2025-09-30T20:50:12+00:00"
    assert turn.final_response is not None
    assert turn.final_response.text == "Готово"
    assert turn.final_response.timestamp.raw == "2025-09-30T20:50:12+00:00"
    assert turn.reasoning
    assert turn.reasoning[0]["type"] == "thought"

    assert turn.llm_request is not None
    assert turn.llm_request.messages
    assert turn.llm_request.messages[-1]["content"] == "Переведи требования"

    assert turn.tool_calls
    tool_event = turn.tool_calls[0]
    assert tool_event.summary.index == 1
    assert tool_event.call_identifier == "tool-1"
    assert tool_event.raw_data is None
    assert isinstance(tool_event.summary.raw_payload, Mapping)
    assert tool_event.timestamp.raw == "2025-09-30T20:50:10+00:00"
    assert not tool_event.timestamp.missing

    assert turn.events
    assert turn.events[0].kind == "response"
    assert turn.events[-1].kind == "tool"
    assert turn.events[-1].tool_call is tool_event

    assert turn.raw_payload is not None
    assert turn.raw_payload["answer"] == "Готово"

    assert entry_timeline.layout_hints == {"user": 140, "agent": 220}
    assert entry_timeline.can_regenerate is True


def test_tool_calls_sorted_by_timestamp() -> None:
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
    turn = timeline.entries[0].agent_turn
    assert turn is not None

    tool_ids = [details.call_identifier for details in turn.tool_calls]
    assert tool_ids == ["tool-1", "tool-4", "tool-6"]
    assert [details.summary.index for details in turn.tool_calls] == [1, 2, 3]

    event_ids = [
        event.tool_call.call_identifier
        for event in turn.events
        if event.kind == "tool" and event.tool_call is not None
    ]
    assert event_ids == tool_ids


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
    turn = timeline.entries[0].agent_turn
    assert turn is not None
    tool_event = turn.tool_calls[0]

    raw_data = tool_event.raw_data
    assert isinstance(raw_data, Mapping)
    call_payload = raw_data.get("llm_request")
    assert isinstance(call_payload, Mapping)
    assert call_payload.get("arguments", {}).get("rid") == "DEMO16"
    response_payload = raw_data.get("llm_response")
    assert isinstance(response_payload, Mapping)
    assert response_payload.get("content") == "Applying updates"
    assert raw_data.get("step") in (1, "1")


def test_tool_call_event_synthesises_request_when_missing() -> None:
    entry = ChatEntry(
        prompt="",
        response="",
        tokens=1,
        prompt_at="2025-10-01T09:00:00+00:00",
        response_at="2025-10-01T09:00:05+00:00",
        tool_results=[
            {
                "tool_name": "update_requirement_field",
                "tool_call_id": "call-42",
                "arguments": {
                    "rid": "REQ-9",
                    "field": "title",
                    "value": "Updated title",
                },
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "missing rid",
                },
            }
        ],
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)
    turn = timeline.entries[0].agent_turn
    assert turn is not None
    tool_event = turn.tool_calls[0]

    raw_data = tool_event.raw_data
    assert isinstance(raw_data, Mapping)
    arguments = raw_data.get("llm_request", {}).get("arguments")
    assert isinstance(arguments, Mapping)
    assert arguments.get("rid") == "REQ-9"
    assert arguments.get("field") == "title"
    assert arguments.get("value") == "Updated title"

    events = [event for event in turn.events if event.kind == "tool"]
    assert events and events[0].tool_call is tool_event


def test_streamed_responses_in_turn() -> None:
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
    turn = timeline.entries[0].agent_turn
    assert turn is not None

    assert turn.streamed_responses
    step_event = turn.streamed_responses[0]
    assert step_event.text == "Preparing request"
    assert step_event.step_index == 1
    assert step_event.is_final is False

    final_event = turn.final_response
    assert final_event is not None
    assert final_event.text == "Final result"
    assert final_event.is_final is True

    # the streaming step with the same text as the final response is deduplicated
    assert all(resp.text != final_event.text for resp in turn.streamed_responses)


def test_promotes_last_stream_when_final_missing() -> None:
    entry = ChatEntry(
        prompt="draft",
        response="",
        tokens=1,
        prompt_at="2025-10-01T08:00:00+00:00",
        response_at=None,
        raw_result={
            "diagnostic": {
                "llm_steps": [
                    {
                        "step": 1,
                        "response": {
                            "content": "Streamed answer",
                            "timestamp": "2025-10-01T08:00:07+00:00",
                        },
                    }
                ]
            }
        },
        tool_results=[
            {
                "tool_name": "demo_tool",
                "completed_at": "2025-10-01T08:00:09+00:00",
            }
        ],
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)
    turn = timeline.entries[0].agent_turn
    assert turn is not None

    assert turn.final_response is not None
    assert turn.final_response.text == "Streamed answer"
    assert turn.final_response.is_final is True
    assert not turn.streamed_responses
    assert turn.timestamp.raw == "2025-10-01T08:00:07+00:00"
    assert turn.timestamp.source == "llm_step"


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
    turn = timeline.entries[0].agent_turn
    assert turn is not None
    summary = turn.tool_calls[0].summary

    assert summary.status == "failed"
    assert any("Error VALIDATION_ERROR" in line for line in summary.bullet_lines)
    assert not any(line.startswith("Error message:") for line in summary.bullet_lines)


def test_tool_summary_includes_diagnostics_metadata() -> None:
    entry = ChatEntry(
        prompt="",
        response="",
        tokens=1,
        prompt_at="2025-10-01T08:00:00+00:00",
        response_at="2025-10-01T08:05:00+00:00",
        tool_results=[
            {
                "tool_name": "update_requirement_field",
                "tool_call_id": "tool-42",
                "arguments": {"rid": "REQ-9", "field": "title"},
                "started_at": "2025-10-01T08:01:00+00:00",
                "completed_at": "2025-10-01T08:01:02+00:00",
                "duration_ms": 2150,
                "cost": {"display": "$0.01"},
                "ok": False,
                "error": {"message": "validation failed"},
            }
        ],
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)
    turn = timeline.entries[0].agent_turn
    assert turn is not None
    summary = turn.tool_calls[0].summary

    assert summary.duration is not None
    assert summary.duration == pytest.approx(2.15, rel=1e-6)
    assert summary.cost == "$0.01"
    assert summary.error_message == "validation failed"
    assert isinstance(summary.arguments, Mapping)
    assert summary.arguments["rid"] == "REQ-9"

def test_llm_request_sequence_preserved() -> None:
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
    turn = timeline.entries[0].agent_turn
    assert turn is not None
    llm_snapshot = turn.llm_request
    assert llm_snapshot is not None
    assert llm_snapshot.messages[0]["role"] == "system"
    assert llm_snapshot.messages[-1]["content"] == "translate"
    assert llm_snapshot.sequence is not None
    assert llm_snapshot.sequence[0]["step"] == 1


def test_missing_timestamps_reported_as_missing() -> None:
    entry = ChatEntry(
        prompt="hello",
        response="",
        tokens=1,
        tool_results=[{"tool_name": "noop"}],
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)
    entry_timeline = timeline.entries[0]

    assert entry_timeline.prompt is not None
    assert entry_timeline.prompt.timestamp.raw is None
    assert entry_timeline.prompt.timestamp.missing is True

    turn = entry_timeline.agent_turn
    assert turn is not None
    assert turn.timestamp.raw is None
    assert turn.timestamp.missing is True
    assert turn.timestamp.source == "response_at"
    assert turn.tool_calls

    raw_section = turn.raw_payload
    assert raw_section is None or isinstance(raw_section, Mapping)


def test_chat_entry_from_dict_preserves_reasoning_whitespace() -> None:
    payload = {
        "prompt": "",
        "response": "",
        "tokens": 0,
        "token_info": {"tokens": 0, "approximate": False},
        "reasoning": [
            {
                "type": "analysis",
                "text": "План",
                "leading_whitespace": " ",
                "trailing_whitespace": " \n",
            }
        ],
    }

    entry = ChatEntry.from_dict(payload)

    assert entry.reasoning == (
        {
            "type": "analysis",
            "text": "План",
            "leading_whitespace": " ",
            "trailing_whitespace": " \n",
        },
    )
