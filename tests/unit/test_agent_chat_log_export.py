from __future__ import annotations

from datetime import UTC, datetime
import json

from app.agent.run_contract import (
    AgentRunPayload,
    LlmStep,
    LlmTrace,
    ToolError,
    ToolMetrics,
    ToolResultSnapshot,
    ToolTimelineEvent,
)
from app.llm.spec import SYSTEM_PROMPT
from app.ui.agent_chat_panel.log_export import (
    SYSTEM_PROMPT_PLACEHOLDER,
    compose_transcript_log_text,
    compose_transcript_text,
)
from app.ui.chat_entry import ChatConversation, ChatEntry


_SYSTEM_PROMPT_TEXT = str(SYSTEM_PROMPT).strip()


def _iso(ts: str) -> str:
    return datetime.fromisoformat(ts).astimezone(UTC).isoformat()


def _snapshot(
    *,
    call_id: str,
    tool_name: str,
    status: str,
    started_at: str,
    completed_at: str | None = None,
    last_observed_at: str | None = None,
    arguments: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
    error: ToolError | None = None,
) -> ToolResultSnapshot:
    events = [
        ToolTimelineEvent(kind="started", occurred_at=started_at, message="started"),
    ]
    if completed_at is not None:
        events.append(
            ToolTimelineEvent(
                kind="completed" if status == "succeeded" else "failed",
                occurred_at=completed_at,
                message="completed" if status == "succeeded" else "failed",
            )
        )
    metrics = ToolMetrics(
        duration_seconds=None,
        cost=None,
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
        last_observed_at=last_observed_at or completed_at or started_at,
        metrics=metrics,
    )


def _conversation_with_failed_updates() -> ChatConversation:
    conversation = ChatConversation.new()
    prompt_text = "Переведи выделенные требования на русский (включая названия) и сохрани"
    response_text = (
        "VALIDATION_ERROR: update_requirement_field() missing 1 required positional argument: 'rid'"
    )

    success_snapshot = _snapshot(
        call_id="tool-1",
        tool_name="get_requirement",
        status="succeeded",
        started_at="2025-10-02T11:19:15+00:00",
        completed_at="2025-10-02T11:19:16+00:00",
        arguments={"rid": "DEMO17"},
        result={"items": [{"rid": "DEMO17"}, {"rid": "DEMO18"}]},
    )

    error_payload = ToolError(
        message="update_requirement_field() missing 1 required positional argument: 'rid'",
        code="VALIDATION_ERROR",
        details={"field": "title"},
    )

    failure_snapshots = [
        _snapshot(
            call_id=f"tool-{index}",
            tool_name="update_requirement_field",
            status="failed",
            started_at=stamp,
            completed_at=stamp,
            arguments={
                "rid": f"DEMO{16 + index}",
                "field": "title" if index % 2 else "statement",
                "value": "Тестовое значение",
            },
            error=error_payload,
        )
        for index, stamp in enumerate(
            [
                "2025-10-02T11:27:02+00:00",
                "2025-10-02T11:28:10+00:00",
                "2025-10-02T11:31:28+00:00",
                "2025-10-02T11:35:56+00:00",
                "2025-10-02T11:38:04+00:00",
            ],
            start=2,
        )
    ]

    payload = AgentRunPayload(
        ok=False,
        status="failed",
        result_text=response_text,
        reasoning=(),
        tool_results=[success_snapshot, *failure_snapshots],
        llm_trace=LlmTrace(),
        diagnostic={
            "llm_request_messages": (
                {"role": "system", "content": _SYSTEM_PROMPT_TEXT},
                {"role": "user", "content": prompt_text},
            ),
            "llm_request_messages_sequence": (
                {
                    "step": 1,
                    "messages": (
                        {"role": "system", "content": _SYSTEM_PROMPT_TEXT},
                        {"role": "user", "content": prompt_text},
                    ),
                },
                {
                    "step": 2,
                    "messages": (
                        {"role": "system", "content": _SYSTEM_PROMPT_TEXT},
                        {
                            "role": "assistant",
                            "content": "Calling update_requirement_field",
                        },
                    ),
                },
            ),
        },
    )

    entry = ChatEntry(
        prompt=prompt_text,
        response="",
        display_response=None,
        tokens=0,
        prompt_at=_iso("2025-10-02T11:19:15+00:00"),
        response_at=_iso("2025-10-02T11:38:04+00:00"),
        raw_result=payload.to_dict(),
        diagnostic=dict(payload.diagnostic or {}),
    )
    conversation.append_entry(entry)
    return conversation


def _conversation_with_streamed_responses() -> ChatConversation:
    conversation = ChatConversation.new()
    prompt_text = "Привет"
    llm_trace = LlmTrace(
        steps=[
            LlmStep(
                index=1,
                occurred_at="2025-10-02T11:00:03+00:00",
                request=(),
                response={"content": "Обрабатываю запрос"},
            ),
            LlmStep(
                index=2,
                occurred_at="2025-10-02T11:00:05+00:00",
                request=(),
                response={"content": "Готово: итоговое сообщение"},
            ),
        ]
    )
    payload = AgentRunPayload(
        ok=True,
        status="succeeded",
        result_text="Готово: итоговое сообщение",
        reasoning=(),
        tool_results=[],
        llm_trace=llm_trace,
        diagnostic={},
    )
    entry = ChatEntry(
        prompt=prompt_text,
        response="",
        display_response=None,
        tokens=0,
        prompt_at=_iso("2025-10-02T11:00:00+00:00"),
        response_at=_iso("2025-10-02T11:00:05+00:00"),
        raw_result=payload.to_dict(),
        diagnostic={},
    )
    conversation.append_entry(entry)
    return conversation


def test_plain_transcript_uses_agent_turn_text_and_tool_summaries() -> None:
    conversation = _conversation_with_failed_updates()

    plain_text = compose_transcript_text(conversation)

    assert "VALIDATION_ERROR" in plain_text
    assert "Waiting for agent response" not in plain_text
    assert "1. [02 Oct 2025 11:19:15] You:" in plain_text
    assert "[02 Oct 2025 11:38:04] Agent:" in plain_text
    assert "Agent: tool call 1: get_requirement — completed" in plain_text
    assert "Agent: tool call 2: update_requirement_field — failed" in plain_text
    assert (
        "• Error: update_requirement_field() missing 1 required positional argument: 'rid'"
        in plain_text
    )


def test_plain_transcript_includes_streamed_responses() -> None:
    conversation = _conversation_with_streamed_responses()

    plain_text = compose_transcript_text(conversation)

    assert "[02 Oct 2025 11:00:03] Agent (step 1):" in plain_text
    assert "Обрабатываю запрос" in plain_text
    assert "[02 Oct 2025 11:00:05] Agent:" in plain_text
    assert "Готово: итоговое сообщение" in plain_text
    assert "Waiting for agent response" not in plain_text


def test_transcript_log_replaces_repeated_system_prompt() -> None:
    conversation = _conversation_with_failed_updates()

    log_text = compose_transcript_log_text(conversation)
    encoded_prompt = json.dumps(_SYSTEM_PROMPT_TEXT, ensure_ascii=False)

    assert log_text.count(encoded_prompt) == 1
    assert log_text.count(SYSTEM_PROMPT_PLACEHOLDER) >= 1


def test_transcript_log_replaces_prefixed_system_prompt_but_keeps_context() -> None:
    conversation = ChatConversation.new()
    prompt_text = "Переведи требования"
    combined_prompt = _SYSTEM_PROMPT_TEXT + "\n\nContext:\n- File: README.md"
    payload = AgentRunPayload(
        ok=True,
        status="succeeded",
        result_text="Готово",
        reasoning=(),
        tool_results=[],
        llm_trace=LlmTrace(),
        diagnostic={
            "llm_request_messages": (
                {"role": "system", "content": combined_prompt},
                {"role": "user", "content": prompt_text},
            )
        },
    )
    entry = ChatEntry(
        prompt=prompt_text,
        response="Готово",
        display_response=None,
        tokens=0,
        prompt_at=_iso("2025-10-02T12:00:00+00:00"),
        response_at=_iso("2025-10-02T12:00:05+00:00"),
        raw_result=payload.to_dict(),
        diagnostic=dict(payload.diagnostic or {}),
    )
    entry.context_messages = (
        {"role": "system", "content": combined_prompt},
        {"role": "user", "content": "Context item"},
    )
    conversation.append_entry(entry)

    log_text = compose_transcript_log_text(conversation)

    assert log_text.count(json.dumps(combined_prompt, ensure_ascii=False)) == 1
    assert SYSTEM_PROMPT_PLACEHOLDER in log_text
    assert "Context item" in log_text


def test_transcript_log_sanitises_raw_payload_prompts() -> None:
    conversation = _conversation_with_failed_updates()

    log_text = compose_transcript_log_text(conversation)

    assert log_text.count(SYSTEM_PROMPT_PLACEHOLDER) >= 2
