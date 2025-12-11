from app.agent.run_contract import (
    AgentEvent,
    AgentEventLog,
    AgentRunPayload,
    LlmStep,
    LlmTrace,
    ToolResultSnapshot,
    build_agent_timeline,
)


def test_build_agent_timeline_uses_event_order_and_snapshots() -> None:
    event_log = AgentEventLog(
        events=[
            AgentEvent(
                kind="llm_step",
                occurred_at="2024-01-01T00:00:00Z",
                payload={"index": 1},
                sequence=5,
            ),
            AgentEvent(
                kind="tool_started",
                occurred_at="2024-01-01T00:00:01Z",
                payload={"call_id": "tool-1", "tool_name": "demo"},
                sequence=6,
            ),
            AgentEvent(
                kind="agent_finished",
                occurred_at="2024-01-01T00:00:02Z",
                payload={"ok": True, "status": "succeeded"},
                sequence=10,
            ),
        ]
    )

    snapshots = [
        ToolResultSnapshot(
            call_id="tool-1",
            tool_name="demo",
            status="succeeded",
            started_at="2024-01-01T00:00:01Z",
            completed_at="2024-01-01T00:00:02Z",
        )
    ]
    llm_trace = LlmTrace(
        steps=[
            LlmStep(
                index=1,
                occurred_at="2024-01-01T00:00:00Z",
                request=(),
                response={"content": "hi"},
            )
        ]
    )

    timeline = build_agent_timeline(
        event_log, tool_results=snapshots, llm_trace=llm_trace
    )

    assert [(entry.kind, entry.sequence) for entry in timeline] == [
        ("llm_step", 5),
        ("tool_call", 6),
        ("agent_finished", 10),
    ]
    assert timeline[1].call_id == "tool-1"
    assert timeline[1].status == "succeeded"


def test_agent_run_payload_rebuilds_timeline_when_missing() -> None:
    event_log = AgentEventLog(
        events=[
            AgentEvent(
                kind="tool_completed",
                occurred_at="2024-01-01T00:00:01Z",
                payload={"call_id": "tool-1", "status": "failed"},
                sequence=0,
            ),
        ]
    )
    llm_trace = LlmTrace(
        steps=[
            LlmStep(
                index=0,
                occurred_at="2024-01-01T00:00:00Z",
                request=(),
                response={},
            )
        ]
    )
    snapshots = [
        ToolResultSnapshot(
            call_id="tool-1",
            tool_name="demo",
            status="failed",
            started_at="2024-01-01T00:00:01Z",
            completed_at="2024-01-01T00:00:02Z",
        ),
        ToolResultSnapshot(
            call_id="tool-2",
            tool_name="demo",
            status="running",
            started_at="2024-01-01T00:00:03Z",
        ),
    ]

    payload = AgentRunPayload(
        ok=False,
        status="failed",
        result_text="",
        events=event_log,
        tool_results=snapshots,
        llm_trace=llm_trace,
        reasoning=(),
    )
    raw = payload.to_dict()
    raw.pop("timeline", None)

    parsed = AgentRunPayload.from_dict(raw)

    assert [entry.kind for entry in parsed.timeline] == [
        "tool_call",
        "llm_step",
        "tool_call",
    ]
    assert [entry.call_id for entry in parsed.timeline if entry.call_id] == [
        "tool-1",
        "tool-2",
    ]
    assert parsed.timeline[0].sequence == 0
    assert parsed.timeline[-1].sequence > parsed.timeline[0].sequence
