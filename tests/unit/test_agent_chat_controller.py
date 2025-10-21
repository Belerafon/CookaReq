from __future__ import annotations

from collections.abc import Mapping

from app.ui.agent_chat_panel.controller import AgentRunController
from app.ui.agent_chat_panel.execution import _AgentRunHandle
from app.llm.tokenizer import TokenCountResult
from app.util.cancellation import CancellationEvent


def _handle(run_id: int = 1) -> _AgentRunHandle:
    return _AgentRunHandle(
        run_id=run_id,
        prompt="demo",
        prompt_tokens=TokenCountResult.exact(0),
        cancel_event=CancellationEvent(),
        prompt_at="2025-10-02T00:00:00Z",
    )


def test_prepare_llm_step_payload_updates_preview_and_reasoning() -> None:
    handle = _handle()

    payload: Mapping[str, object] = {
        "step": 1,
        "response": {
            "content": "Interpreting request",
            "reasoning": [
                {"type": "analysis", "text": "First", "trailing_whitespace": " "},
                {
                    "type": "thinking",
                    "text": "Second",
                    "leading_whitespace": " ",
                    "trailing_whitespace": " ",
                },
            ],
        },
    }

    safe_payload = AgentRunController._prepare_llm_step_payload(handle, payload)

    assert isinstance(safe_payload, Mapping)
    assert safe_payload["step"] == 1
    assert safe_payload["response"] == {
        "content": "Interpreting request",
        "reasoning": [
            {"type": "analysis", "text": "First", "trailing_whitespace": " "},
            {
                "type": "thinking",
                "text": "Second",
                "leading_whitespace": " ",
                "trailing_whitespace": " ",
            },
        ],
    }
    assert handle.llm_trace_preview == [safe_payload]
    assert handle.latest_llm_response == "Interpreting request"
    assert handle.latest_reasoning_segments == (
        {"type": "analysis", "text": "First", "trailing_whitespace": " "},
        {
            "type": "thinking",
            "text": "Second",
            "leading_whitespace": " ",
            "trailing_whitespace": " ",
        },
    )

    replacement = AgentRunController._prepare_llm_step_payload(
        handle,
        {
            "step": 1,
            "response": {
                "content": "Updated",
                "reasoning": [
                    {"type": "analysis", "text": "First"},
                    {"type": "thinking", "text": "Updated"},
                ],
            },
        },
    )

    assert handle.llm_trace_preview == [replacement]
    assert handle.latest_llm_response == "Updated"


def test_prepare_llm_step_payload_ignores_non_mapping_payload() -> None:
    handle = _handle()

    result = AgentRunController._prepare_llm_step_payload(handle, 42)  # type: ignore[arg-type]

    assert result is None
    assert handle.llm_trace_preview == []


def test_record_tool_snapshot_preserves_order_and_updates_entries() -> None:
    handle = _handle()

    first_snapshot = {
        "call_id": "tool-1",
        "tool_name": "get_requirement",
        "status": "running",
        "events": [
            {
                "kind": "started",
                "occurred_at": "2025-10-02T06:58:26+00:00",
                "message": "started",
            }
        ],
        "started_at": "2025-10-02T06:58:26+00:00",
        "last_observed_at": "2025-10-02T06:58:26+00:00",
        "arguments": {"rid": "DEMO-1"},
    }

    ordered = handle.record_tool_snapshot(first_snapshot)

    assert [snapshot.call_id for snapshot in ordered] == ["tool-1"]
    assert ordered[0].status == "running"

    second_snapshot = {
        "call_id": "tool-2",
        "tool_name": "update_requirement_field",
        "status": "pending",
        "events": [
            {
                "kind": "started",
                "occurred_at": "2025-10-02T06:59:00+00:00",
                "message": "waiting",
            }
        ],
        "started_at": "2025-10-02T06:59:00+00:00",
    }

    ordered = handle.record_tool_snapshot(second_snapshot)

    assert [snapshot.call_id for snapshot in ordered] == ["tool-1", "tool-2"]

    completion = {
        "call_id": "tool-1",
        "tool_name": "get_requirement",
        "status": "succeeded",
        "events": [
            {
                "kind": "completed",
                "occurred_at": "2025-10-02T06:58:30+00:00",
                "message": "done",
            }
        ],
        "started_at": "2025-10-02T06:58:26+00:00",
        "completed_at": "2025-10-02T06:58:30+00:00",
        "last_observed_at": "2025-10-02T06:58:30+00:00",
        "result": {"items": [{"rid": "DEMO-1"}]},
    }

    ordered = handle.record_tool_snapshot(completion)
    assert [snapshot.call_id for snapshot in ordered] == ["tool-1", "tool-2"]

    updated = handle.tool_snapshots["tool-1"]
    assert updated.status == "succeeded"
    assert updated.completed_at == "2025-10-02T06:58:30+00:00"
    assert updated.result == {"items": [{"rid": "DEMO-1"}]}


def test_record_tool_snapshot_generates_identifier_when_missing() -> None:
    handle = _handle(run_id=7)

    snapshot_payload = {
        "tool_name": "update_requirement_field",
        "status": "running",
        "events": [
            {
                "kind": "started",
                "occurred_at": "2025-10-02T07:10:00+00:00",
                "message": "invoked",
            }
        ],
    }

    ordered = handle.record_tool_snapshot(snapshot_payload)

    assert len(ordered) == 1
    generated_id = ordered[0].call_id
    assert generated_id == "7:tool:1"
    assert handle.tool_order == [generated_id]


def test_record_tool_snapshot_ignores_invalid_payload() -> None:
    handle = _handle()

    handle.record_tool_snapshot(
        {
            "call_id": "tool-1",
            "tool_name": "get_requirement",
            "status": "running",
            "events": [
                {
                    "kind": "started",
                    "occurred_at": "2025-10-02T08:00:00+00:00",
                }
            ],
        }
    )

    ordered = handle.record_tool_snapshot({"call_id": "tool-2"})

    assert [snapshot.call_id for snapshot in ordered] == ["tool-1"]
    assert "tool-2" not in handle.tool_snapshots
