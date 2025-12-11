import pytest

from app.agent.run_contract import (
    AgentEvent,
    AgentEventLog,
    LlmStep,
    LlmTrace,
    ToolResultSnapshot,
    build_timeline_debug,
)


@pytest.mark.parametrize("status", ["running", "succeeded"])
def test_build_timeline_debug_includes_unfinished_tool(status: str) -> None:
    event_log = AgentEventLog(
        events=[
            AgentEvent(
                kind="llm_step",
                occurred_at="2024-01-01T00:00:00Z",
                payload={"index": 0},
                sequence=0,
            ),
            AgentEvent(
                kind="tool_started",
                occurred_at="2024-01-01T00:00:01Z",
                payload={"call_id": "tool-1", "tool_name": "demo"},
                sequence=1,
            ),
            AgentEvent(
                kind="agent_finished",
                occurred_at="2024-01-01T00:00:02Z",
                payload={},
                sequence=2,
            ),
        ]
    )

    llm_trace = LlmTrace(
        steps=[
            LlmStep(index=0, occurred_at="2024-01-01T00:00:00Z", request=(), response={}),
            LlmStep(index=1, occurred_at="2024-01-01T00:00:02Z", request=(), response={}),
        ]
    )
    snapshots = [
        ToolResultSnapshot(
            call_id="tool-1",
            tool_name="demo",
            status=status,
            started_at="2024-01-01T00:00:01Z",
        )
    ]

    timeline = build_timeline_debug(event_log, tool_results=snapshots, llm_trace=llm_trace)

    assert [entry["kind"] for entry in timeline[:3]] == [
        "llm_step",
        "tool_started",
        "agent_finished",
    ]
    assert timeline[1]["call_id"] == "tool-1"
    assert {entry["source"] for entry in timeline} == {
        "event_log",
        "llm_trace",
        "tool_snapshot",
    }
    tool_entries = [entry for entry in timeline if entry["source"] == "tool_snapshot"]
    assert tool_entries and tool_entries[0]["call_id"] == "tool-1"
    assert tool_entries[0]["status"] == status
    llm_sources = [entry for entry in timeline if entry["source"] == "llm_trace"]
    assert [entry["step_index"] for entry in llm_sources] == [0, 1]
