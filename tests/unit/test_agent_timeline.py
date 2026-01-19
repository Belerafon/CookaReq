from app.agent.run_contract import (
    AgentEvent,
    AgentEventLog,
    AgentRunPayload,
    AgentTimelineEntry,
    LlmStep,
    LlmTrace,
    ToolResultSnapshot,
    build_agent_timeline,
)
import datetime as _dt

from app.agent.timeline_utils import assess_timeline_integrity, timeline_checksum
from app.ui.agent_chat_panel.tool_summaries import ToolCallSummary
from app.ui.agent_chat_panel.view_model import (
    AgentResponse,
    TimestampInfo,
    ToolCallDetails,
    _build_agent_events,
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
        ("llm_step", 0),
        ("tool_call", 1),
        ("agent_finished", 2),
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
        "llm_step",
        "tool_call",
        "tool_call",
    ]
    assert [entry.call_id for entry in parsed.timeline if entry.call_id] == [
        "tool-1",
        "tool-2",
    ]
    assert [entry.sequence for entry in parsed.timeline] == [0, 1, 2]


def test_build_agent_timeline_merges_tool_snapshots_without_tool_events() -> None:
    event_log = AgentEventLog(
        events=[
            AgentEvent(
                kind="llm_step",
                occurred_at="2024-01-01T00:00:00Z",
                payload={"index": 1},
                sequence=0,
            ),
            AgentEvent(
                kind="llm_step",
                occurred_at="2024-01-01T00:00:05Z",
                payload={"index": 2},
                sequence=1,
            ),
            AgentEvent(
                kind="agent_finished",
                occurred_at="2024-01-01T00:00:10Z",
                payload={"ok": True, "status": "succeeded"},
                sequence=2,
            ),
        ]
    )
    snapshots = [
        ToolResultSnapshot(
            call_id="call-1",
            tool_name="alpha",
            status="succeeded",
            started_at="2024-01-01T00:00:02Z",
            completed_at="2024-01-01T00:00:03Z",
        ),
        ToolResultSnapshot(
            call_id="call-2",
            tool_name="beta",
            status="succeeded",
            started_at="2024-01-01T00:00:07Z",
            completed_at="2024-01-01T00:00:08Z",
        ),
    ]
    llm_trace = LlmTrace(
        steps=[
            LlmStep(
                index=1,
                occurred_at="2024-01-01T00:00:00Z",
                request=(),
                response={
                    "content": "step1",
                    "tool_calls": [{"id": "call-1", "name": "alpha", "arguments": {}}],
                },
            ),
            LlmStep(
                index=2,
                occurred_at="2024-01-01T00:00:05Z",
                request=(),
                response={
                    "content": "step2",
                    "tool_calls": [{"id": "call-2", "name": "beta", "arguments": {}}],
                },
            ),
        ]
    )

    timeline = build_agent_timeline(
        event_log, tool_results=snapshots, llm_trace=llm_trace
    )

    assert [entry.kind for entry in timeline] == [
        "llm_step",
        "tool_call",
        "llm_step",
        "tool_call",
        "agent_finished",
    ]
    assert [entry.sequence for entry in timeline] == list(range(5))
    assert [entry.step_index for entry in timeline if entry.kind == "tool_call"] == [
        1,
        2,
    ]


def test_build_agent_timeline_normalizes_sequence_contiguity() -> None:
    event_log = AgentEventLog(
        events=[
            AgentEvent(
                kind="llm_step",
                occurred_at="2024-01-01T00:00:00Z",
                payload={"index": 1},
                sequence=10,
            ),
            AgentEvent(
                kind="tool_started",
                occurred_at="2024-01-01T00:00:01Z",
                payload={"call_id": "tool-1", "tool_name": "demo"},
                sequence=20,
            ),
            AgentEvent(
                kind="agent_finished",
                occurred_at="2024-01-01T00:00:02Z",
                payload={"ok": True, "status": "succeeded"},
                sequence=30,
            ),
        ]
    )

    timeline = build_agent_timeline(event_log)

    assert [entry.kind for entry in timeline] == [
        "llm_step",
        "tool_call",
        "agent_finished",
    ]
    assert [entry.sequence for entry in timeline] == [0, 1, 2]


def test_timeline_checksum_is_order_sensitive_and_stable() -> None:
    timeline_a = tuple(
        build_agent_timeline(
            AgentEventLog(
                events=[
                    AgentEvent(
                        kind="llm_step",
                        occurred_at="2024-01-01T00:00:00Z",
                        payload={"index": 1},
                        sequence=1,
                    ),
                    AgentEvent(
                        kind="tool_started",
                        occurred_at="2024-01-01T00:00:01Z",
                        payload={"call_id": "tool-1", "tool_name": "demo"},
                        sequence=2,
                    ),
                    AgentEvent(
                        kind="agent_finished",
                        occurred_at="2024-01-01T00:00:02Z",
                        payload={"ok": True, "status": "succeeded"},
                        sequence=3,
                    ),
                ]
            ),
            tool_results=[
                ToolResultSnapshot(
                    call_id="tool-1",
                    tool_name="demo",
                    status="succeeded",
                    started_at="2024-01-01T00:00:01Z",
                    completed_at="2024-01-01T00:00:02Z",
                )
            ],
            llm_trace=LlmTrace(
                steps=[
                    LlmStep(
                        index=1,
                        occurred_at="2024-01-01T00:00:00Z",
                        request=(),
                        response={"content": "hi"},
                    )
                ]
            ),
        )
    )

    timeline_b = tuple(entry for entry in timeline_a)
    assert timeline_checksum(timeline_a) == timeline_checksum(timeline_b)

    reversed_timeline = tuple(reversed(timeline_a))
    assert timeline_checksum(timeline_a) != timeline_checksum(reversed_timeline)


def test_agent_run_payload_roundtrip_preserves_timeline_checksum() -> None:
    timeline = [
        AgentTimelineEntry(
            kind="llm_step",
            occurred_at="2024-01-01T00:00:00Z",
            sequence=1,
            step_index=1,
        ),
        AgentTimelineEntry(
            kind="agent_finished",
            occurred_at="2024-01-01T00:00:01Z",
            sequence=2,
            status="succeeded",
        ),
    ]
    checksum = timeline_checksum(timeline)
    payload = AgentRunPayload(
        ok=True,
        status="succeeded",
        result_text="done",
        events=AgentEventLog(),
        llm_trace=LlmTrace(),
        timeline=timeline,
        timeline_checksum=checksum,
    )

    serialized = payload.to_dict()
    assert serialized["timeline_checksum"] == checksum

    parsed = AgentRunPayload.from_dict(serialized)
    assert parsed.timeline_checksum == checksum
    assert [entry.kind for entry in parsed.timeline] == ["llm_step", "agent_finished"]


def test_agent_run_payload_derives_checksum_when_missing_from_payload() -> None:
    timeline = [
        AgentTimelineEntry(
            kind="llm_step",
            occurred_at="2024-01-01T00:00:00Z",
            sequence=1,
            step_index=1,
        ),
        AgentTimelineEntry(
            kind="tool_call",
            occurred_at="2024-01-01T00:00:01Z",
            sequence=2,
            call_id="tool-1",
            status="succeeded",
        ),
    ]
    raw_payload = AgentRunPayload(
        ok=True,
        status="succeeded",
        result_text="done",
        events=AgentEventLog(),
        llm_trace=LlmTrace(),
        timeline=timeline,
    ).to_dict()
    raw_payload.pop("timeline_checksum", None)

    parsed = AgentRunPayload.from_dict(raw_payload)
    assert parsed.timeline_checksum == timeline_checksum(timeline)


def test_assess_timeline_integrity_detects_mismatch_and_gaps() -> None:
    timeline = (
        AgentTimelineEntry(
            kind="llm_step",
            occurred_at="2024-01-01T00:00:00Z",
            sequence=1,
            step_index=1,
        ),
        AgentTimelineEntry(
            kind="tool_call",
            occurred_at="2024-01-01T00:00:01Z",
            sequence=3,
            call_id="tool-1",
            status="succeeded",
        ),
    )

    integrity = assess_timeline_integrity(timeline, declared_checksum="deadbeef")

    assert integrity.status == "damaged"
    assert "non_contiguous_sequence" in integrity.issues
    assert "checksum_mismatch" in integrity.issues
    assert integrity.checksum == timeline_checksum(timeline)


def test_build_agent_events_fallback_renders_final_response_without_timeline() -> None:
    base_timestamp = TimestampInfo(
        raw="2024-01-01T00:00:00Z",
        occurred_at=_dt.datetime(2024, 1, 1, tzinfo=_dt.timezone.utc),
        formatted="",
        missing=False,
        source="test",
    )
    step_response = AgentResponse(
        text="step",
        display_text="step",
        timestamp=base_timestamp,
        step_index=1,
        is_final=False,
    )
    final_response = AgentResponse(
        text="done",
        display_text="done",
        timestamp=TimestampInfo(
            raw="2024-01-01T00:00:05Z",
            occurred_at=_dt.datetime(2024, 1, 1, 0, 0, 5, tzinfo=_dt.timezone.utc),
            formatted="",
            missing=False,
            source="test",
        ),
        step_index=1,
        is_final=True,
    )
    tool_details = ToolCallDetails(
        summary=ToolCallSummary(index=1, tool_name="demo", status="succeeded", bullet_lines=()),
        call_identifier="call-1",
        raw_data=None,
        timestamp=TimestampInfo(
            raw="2024-01-01T00:00:02Z",
            occurred_at=_dt.datetime(2024, 1, 1, 0, 0, 2, tzinfo=_dt.timezone.utc),
            formatted="",
            missing=False,
            source="tool",
        ),
        llm_request=None,
    )

    events = _build_agent_events(
        (step_response,),
        final_response,
        (tool_details,),
        timeline=(),
        timeline_status="damaged",
    )

    assert [event.kind for event in events] == ["response", "response", "tool"]
    assert events[1].response is final_response
    assert events[-1].tool_call is tool_details
