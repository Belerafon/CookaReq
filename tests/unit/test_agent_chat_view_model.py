from __future__ import annotations

from collections.abc import Sequence

from app.agent.run_contract import (
    AgentRunPayload,
    LlmStep,
    LlmTrace,
    ToolError,
    ToolResultSnapshot,
    ToolTimelineEvent,
)
from app.ui.agent_chat_panel.view_model import build_conversation_timeline
from app.ui.chat_entry import ChatConversation, ChatEntry


VALIDATION_ERROR_MESSAGE = (
    "Invalid arguments for update_requirement_field: value: 'in_last_review' "
    "is not one of ['draft', 'in_review', 'approved', 'baselined', 'retired']"
)


def _conversation_with_entry(entry: ChatEntry) -> ChatConversation:
    conversation = ChatConversation(
        conversation_id="conv-1",
        title="Test",
        created_at="2025-09-30T20:50:00+00:00",
        updated_at="2025-09-30T20:50:00+00:00",
    )
    conversation.replace_entries([entry])
    return conversation


def _tool_snapshot(
    *,
    call_id: str,
    tool_name: str,
    status: str,
    started_at: str,
    completed_at: str | None,
    arguments: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
    error: ToolError | None = None,
) -> ToolResultSnapshot:
    events: list[ToolTimelineEvent] = [
        ToolTimelineEvent(kind="started", occurred_at=started_at, message="start"),
    ]
    if completed_at is not None:
        events.append(
            ToolTimelineEvent(
                kind="completed" if status == "succeeded" else "failed",
                occurred_at=completed_at,
                message=status,
            )
        )
    return ToolResultSnapshot(
        call_id=call_id,
        tool_name=tool_name,
        status=status,
        arguments=arguments,
        result=result,
        error=error,
        events=events,
        started_at=started_at,
        completed_at=completed_at,
        last_observed_at=completed_at or started_at,
    )


def _llm_trace_with_tool_request() -> LlmTrace:
    return LlmTrace(
        steps=[
            LlmStep(
                index=1,
                occurred_at="2025-09-30T20:50:11+00:00",
                request=(
                    {"role": "system", "content": "Поддерживай MCP"},
                    {"role": "user", "content": "Переведи требования"},
                ),
                response={
                    "content": "Calling update_requirement_field",
                    "tool_calls": [
                        {
                            "id": "tool-2",
                            "name": "update_requirement_field",
                            "arguments": {
                                "rid": "DEMO17",
                                "field": "title",
                                "value": "Новое название",
                            },
                        }
                    ],
                },
            ),
            LlmStep(
                index=2,
                occurred_at="2025-09-30T20:50:12+00:00",
                request=(),
                response={"content": "Готово"},
            ),
        ]
    )


def test_build_conversation_timeline_compiles_turn() -> None:
    reasoning_segments = (
        {"type": "thought", "text": "Нужно пройтись по каждому требованию"},
    )
    snapshots = (
        _tool_snapshot(
            call_id="tool-1",
            tool_name="get_requirement",
            status="succeeded",
            started_at="2025-09-30T20:50:10+00:00",
            completed_at="2025-09-30T20:50:11+00:00",
            arguments={"rid": "DEMO17"},
            result={"items": [{"rid": "DEMO17"}]},
        ),
        _tool_snapshot(
            call_id="tool-2",
            tool_name="update_requirement_field",
            status="failed",
            started_at="2025-09-30T20:50:11+00:00",
            completed_at="2025-09-30T20:50:12+00:00",
            arguments={
                "rid": "DEMO17",
                "field": "title",
                "value": "Новая формулировка",
            },
            error=ToolError(message=VALIDATION_ERROR_MESSAGE, code="VALIDATION_ERROR"),
        ),
    )
    payload = AgentRunPayload(
        ok=False,
        status="failed",
        result_text="Готово",
        reasoning=reasoning_segments,
        tool_results=list(snapshots),
        llm_trace=_llm_trace_with_tool_request(),
        diagnostic={},
    )
    entry = ChatEntry(
        prompt="Переведи требования",
        response="",
        tokens=10,
        prompt_at="2025-09-30T20:50:10+00:00",
        response_at="2025-09-30T20:50:12+00:00",
        context_messages=(
            {"role": "system", "content": "Поддерживай MCP"},
        ),
        raw_result=payload.to_dict(),
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
    assert turn.reasoning == reasoning_segments

    assert turn.llm_request is not None
    assert turn.llm_request.sequence is not None
    first_step = turn.llm_request.sequence[0]
    assert first_step["step"] == 1
    messages: Sequence[dict[str, object]] = first_step.get("messages", ())
    assert messages
    assert messages[-1]["content"] == "Переведи требования"

    assert len(turn.streamed_responses) == 1
    first_stream = turn.streamed_responses[0]
    assert first_stream.text == "Calling update_requirement_field"
    assert first_stream.timestamp.raw == "2025-09-30T20:50:11+00:00"

    assert len(turn.tool_calls) == 2
    tool_event = turn.tool_calls[0]
    assert tool_event.summary.index == 1
    assert tool_event.call_identifier == "tool-1"
    raw_data = tool_event.raw_data
    assert isinstance(raw_data, dict)
    assert raw_data.get("call_id") == "tool-1"
    assert raw_data.get("tool_name") == "get_requirement"
    assert tool_event.llm_request is None

    failing_event = turn.tool_calls[1]
    assert failing_event.summary.error_message
    assert failing_event.llm_request is not None
    assert failing_event.llm_request.get("tool") == "update_requirement_field"
    assert failing_event.llm_request.get("arguments", {}).get("rid") == "DEMO17"

    assert turn.events
    assert turn.events[0].kind == "response"
    assert turn.events[-1].kind == "tool"
    assert turn.events[-1].tool_call is failing_event

    assert turn.raw_payload is not None
    assert turn.raw_payload["status"] == "failed"

    assert entry_timeline.layout_hints == {"user": 140, "agent": 220}
    assert entry_timeline.can_regenerate is True


def test_build_conversation_timeline_deduplicates_reasoning_only_reply() -> None:
    reasoning_segments = (
        {
            "type": "analysis",
            "text": "Подбираю инструменты",
            "leading_whitespace": "",
            "trailing_whitespace": "",
        },
    )
    payload = AgentRunPayload(
        ok=True,
        status="succeeded",
        result_text="Подбираю инструменты",
        reasoning=reasoning_segments,
        tool_results=[],
        llm_trace=LlmTrace(
            steps=[
                LlmStep(
                    index=1,
                    occurred_at="2025-09-30T21:00:00+00:00",
                    request=(),
                    response={"content": "Подбираю инструменты"},
                )
            ]
        ),
        diagnostic={},
    )
    entry = ChatEntry(
        prompt="Что дальше?",
        response="Подбираю инструменты",
        tokens=10,
        prompt_at="2025-09-30T20:59:58+00:00",
        response_at="2025-09-30T21:00:00+00:00",
        raw_result=payload.to_dict(),
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)

    assert len(timeline.entries) == 1
    turn = timeline.entries[0].agent_turn
    assert turn is not None
    assert turn.final_response is None
    assert turn.streamed_responses == ()
    assert turn.reasoning == reasoning_segments
    assert not turn.tool_calls
    assert all(event.kind != "response" for event in turn.events)


def test_tool_calls_sorted_by_timestamp() -> None:
    snapshots = (
        _tool_snapshot(
            call_id="tool-1",
            tool_name="get_requirement",
            status="succeeded",
            started_at="2025-09-30T20:50:10+00:00",
            completed_at="2025-09-30T20:50:11+00:00",
        ),
        _tool_snapshot(
            call_id="tool-4",
            tool_name="update_requirement_field",
            status="failed",
            started_at="2025-09-30T20:52:05+00:00",
            completed_at="2025-09-30T20:52:05+00:00",
        ),
        _tool_snapshot(
            call_id="tool-6",
            tool_name="update_requirement_field",
            status="failed",
            started_at="2025-09-30T20:52:57+00:00",
            completed_at="2025-09-30T20:52:58+00:00",
        ),
    )
    payload = AgentRunPayload(
        ok=False,
        status="failed",
        result_text="",
        reasoning=(),
        tool_results=list(snapshots),
        llm_trace=LlmTrace(),
        diagnostic={},
    )
    entry = ChatEntry(
        prompt="",
        response="",
        tokens=1,
        prompt_at="2025-09-30T20:50:10+00:00",
        response_at="2025-09-30T20:52:58+00:00",
        raw_result=payload.to_dict(),
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
    trace = LlmTrace(
        steps=[
            LlmStep(
                index=1,
                occurred_at="2025-10-01T08:52:35+00:00",
                request=(
                    {"role": "system", "content": "context"},
                    {"role": "user", "content": "prompt"},
                ),
                response={
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
            )
        ]
    )
    snapshot = _tool_snapshot(
        call_id="call-1",
        tool_name="update_requirement_field",
        status="failed",
        started_at="2025-10-01T08:52:35+00:00",
        completed_at="2025-10-01T08:52:39+00:00",
    )
    payload = AgentRunPayload(
        ok=False,
        status="failed",
        result_text="",
        reasoning=(),
        tool_results=[snapshot],
        llm_trace=trace,
        diagnostic={},
    )
    entry = ChatEntry(
        prompt="",
        response="",
        tokens=1,
        prompt_at="2025-10-01T08:52:30+00:00",
        response_at="2025-10-01T08:52:40+00:00",
        raw_result=payload.to_dict(),
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)
    turn = timeline.entries[0].agent_turn
    assert turn is not None
    tool_event = turn.tool_calls[0]

    assert isinstance(tool_event.llm_request, dict)
    assert tool_event.llm_request.get("tool") == "update_requirement_field"
    request_arguments = tool_event.llm_request.get("arguments")
    assert isinstance(request_arguments, dict)
    assert request_arguments.get("rid") == "DEMO16"
    assert request_arguments.get("field") == "title"
    assert request_arguments.get("value") == "Новое название"


def test_tool_call_event_includes_error_details_in_summary() -> None:
    error = ToolError(
        message="Валидация не прошла",
        code="VALIDATION_ERROR",
        details={"field": "title"},
    )
    snapshot = _tool_snapshot(
        call_id="call-1",
        tool_name="update_requirement_field",
        status="failed",
        started_at="2025-10-01T12:00:00+00:00",
        completed_at="2025-10-01T12:00:00+00:00",
        arguments={"rid": "DEMO20", "field": "title"},
        error=error,
    )
    payload = AgentRunPayload(
        ok=False,
        status="failed",
        result_text="",
        reasoning=(),
        tool_results=[snapshot],
        llm_trace=LlmTrace(),
        diagnostic={},
    )
    entry = ChatEntry(
        prompt="",
        response="",
        tokens=1,
        prompt_at="2025-10-01T12:00:00+00:00",
        response_at="2025-10-01T12:00:01+00:00",
        raw_result=payload.to_dict(),
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)
    turn = timeline.entries[0].agent_turn
    assert turn is not None
    summary = turn.tool_calls[0].summary

    assert any("Error:" in line for line in summary.bullet_lines)
    assert summary.error_message is not None


def test_llm_request_sequence_preserved() -> None:
    trace = LlmTrace(
        steps=[
            LlmStep(
                index=1,
                occurred_at="2025-10-02T09:00:00+00:00",
                request=({"role": "system", "content": "sys"},),
                response={"content": "step 1"},
            ),
            LlmStep(
                index=2,
                occurred_at="2025-10-02T09:00:05+00:00",
                request=({"role": "user", "content": "hello"},),
                response={"content": "step 2"},
            ),
        ]
    )
    payload = AgentRunPayload(
        ok=True,
        status="succeeded",
        result_text="done",
        reasoning=(),
        tool_results=[],
        llm_trace=trace,
        diagnostic={},
    )
    entry = ChatEntry(
        prompt="hello",
        response="done",
        tokens=1,
        prompt_at="2025-10-02T09:00:00+00:00",
        response_at="2025-10-02T09:00:06+00:00",
        raw_result=payload.to_dict(),
    )
    conversation = _conversation_with_entry(entry)

    timeline = build_conversation_timeline(conversation)
    turn = timeline.entries[0].agent_turn
    assert turn is not None
    llm_snapshot = turn.llm_request
    assert llm_snapshot is not None
    assert llm_snapshot.sequence is not None
    assert [step["step"] for step in llm_snapshot.sequence] == [1, 2]


def test_missing_timestamps_reported_as_missing() -> None:
    payload = AgentRunPayload(
        ok=True,
        status="succeeded",
        result_text="",
        reasoning=(),
        tool_results=[],
        llm_trace=LlmTrace(),
        diagnostic={},
    )
    entry = ChatEntry(
        prompt="hello",
        response="",
        tokens=1,
        prompt_at=None,
        response_at=None,
        raw_result=payload.to_dict(),
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
    assert turn.tool_calls == ()
