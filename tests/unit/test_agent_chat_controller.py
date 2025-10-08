from app.ui.agent_chat_panel.controller import AgentRunController
from app.ui.agent_chat_panel.execution import _AgentRunHandle
from app.llm.tokenizer import TokenCountResult
from app.util.cancellation import CancellationEvent


def test_capture_llm_step_payload_preserves_reasoning_whitespace() -> None:
    handle = _AgentRunHandle(
        run_id=1,
        prompt="demo",
        prompt_tokens=TokenCountResult.exact(0),
        cancel_event=CancellationEvent(),
        prompt_at="2025-10-02T00:00:00Z",
    )

    payload = {
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

    safe_payload = AgentRunController._capture_llm_step_payload(handle, payload)

    assert safe_payload == {
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
    assert handle.llm_steps == [safe_payload]
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


def test_merge_streamed_tool_result_deduplicates_status_updates() -> None:
    handle = _AgentRunHandle(
        run_id=2,
        prompt="demo",
        prompt_tokens=TokenCountResult.exact(0),
        cancel_event=CancellationEvent(),
        prompt_at="2025-10-02T00:01:00Z",
    )

    initial_payload = {
        "tool_call_id": "tool-1",
        "agent_status": "running",
        "observed_at": "2025-10-03T06:58:26+00:00",
    }

    AgentRunController._merge_streamed_tool_result(handle, dict(initial_payload))

    assert len(handle.streamed_tool_results) == 1
    first_entry = handle.streamed_tool_results[0]
    updates = first_entry.get("status_updates")
    assert isinstance(updates, list)
    assert len(updates) == 1
    running_update = updates[0]
    assert running_update.get("raw") == "running"
    assert running_update.get("status") == "running"
    assert running_update.get("message") == "Applying updates"

    follow_up_payload = {
        "tool_call_id": "tool-1",
        "agent_status": "failed",
        "observed_at": "2025-10-03T06:58:26+00:00",
        "status_updates": [
            {
                "raw": "running",
                "status": "running",
                "at": "2025-10-03T06:58:26+00:00",
            },
            {
                "raw": "failed",
                "status": "failed",
                "at": "2025-10-03T06:58:26+00:00",
            },
        ],
    }

    AgentRunController._merge_streamed_tool_result(handle, dict(follow_up_payload))

    merged_entry = handle.streamed_tool_results[0]
    merged_updates = merged_entry.get("status_updates")
    assert isinstance(merged_updates, list)
    assert [(item.get("raw"), item.get("status")) for item in merged_updates] == [
        ("running", "running"),
        ("failed", "failed"),
    ]

    repeated_payload = {
        "tool_call_id": "tool-1",
        "agent_status": "failed",
        "observed_at": "2025-10-03T06:58:26+00:00",
    }

    AgentRunController._merge_streamed_tool_result(handle, dict(repeated_payload))

    deduplicated_updates = handle.streamed_tool_results[0].get("status_updates")
    assert isinstance(deduplicated_updates, list)
    assert len(deduplicated_updates) == 2
    assert {item.get("raw") for item in deduplicated_updates} == {"running", "failed"}


def test_merge_streamed_tool_result_updates_timestamps() -> None:
    handle = _AgentRunHandle(
        run_id=3,
        prompt="demo",
        prompt_tokens=TokenCountResult.exact(0),
        cancel_event=CancellationEvent(),
        prompt_at="2025-10-02T00:02:00Z",
    )

    AgentRunController._merge_streamed_tool_result(
        handle,
        {
            "tool_call_id": "tool-2",
            "agent_status": "running",
            "observed_at": "2025-10-03T07:00:00+00:00",
        },
    )

    AgentRunController._merge_streamed_tool_result(
        handle,
        {
            "tool_call_id": "tool-2",
            "agent_status": "completed",
            "observed_at": "2025-10-03T07:01:00+00:00",
        },
    )

    assert len(handle.streamed_tool_results) == 1
    merged_entry = handle.streamed_tool_results[0]
    assert merged_entry.get("first_observed_at") == "2025-10-03T07:00:00+00:00"
    assert merged_entry.get("last_observed_at") == "2025-10-03T07:01:00+00:00"
    assert merged_entry.get("completed_at") == "2025-10-03T07:01:00+00:00"


def test_merge_streamed_tool_result_without_identifier_adds_entry() -> None:
    handle = _AgentRunHandle(
        run_id=4,
        prompt="demo",
        prompt_tokens=TokenCountResult.exact(0),
        cancel_event=CancellationEvent(),
        prompt_at="2025-10-02T00:03:00Z",
    )

    payload = {
        "agent_status": "running",
        "observed_at": "2025-10-03T07:05:00+00:00",
    }

    AgentRunController._merge_streamed_tool_result(handle, dict(payload))

    assert len(handle.streamed_tool_results) == 1
    stored_entry = handle.streamed_tool_results[0]
    assert stored_entry.get("status_updates")
    assert stored_entry.get("observed_at") == "2025-10-03T07:05:00+00:00"


def test_merge_streamed_tool_result_preserves_tool_arguments() -> None:
    handle = _AgentRunHandle(
        run_id=5,
        prompt="demo",
        prompt_tokens=TokenCountResult.exact(0),
        cancel_event=CancellationEvent(),
        prompt_at="2025-10-02T00:04:00Z",
    )

    initial_payload = {
        "tool_call_id": "tool-3",
        "agent_status": "running",
        "observed_at": "2025-10-03T07:10:00+00:00",
        "arguments": {"path": "./demo.json"},
    }

    AgentRunController._merge_streamed_tool_result(handle, dict(initial_payload))

    follow_up_payload = {
        "tool_call_id": "tool-3",
        "agent_status": "completed",
        "observed_at": "2025-10-03T07:10:30+00:00",
        "arguments": {"path": "./demo.json", "force": True},
    }

    AgentRunController._merge_streamed_tool_result(handle, dict(follow_up_payload))

    assert len(handle.streamed_tool_results) == 1
    stored_entry = handle.streamed_tool_results[0]
    assert stored_entry.get("arguments") == {"path": "./demo.json", "force": True}
