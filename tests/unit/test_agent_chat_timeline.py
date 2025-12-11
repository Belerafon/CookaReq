from app.agent.run_contract import AgentEvent
from app.agent.run_contract import AgentEvent, AgentTimelineEntry
from app.ui.agent_chat_panel.tool_summaries import ToolCallSummary
from app.ui.agent_chat_panel.view_model import (
    AgentResponse,
    ToolCallDetails,
    _build_agent_events,
    _build_timestamp,
)


def _summary() -> ToolCallSummary:
    return ToolCallSummary(
        index=1,
        tool_name="update_requirement_field",
        status="succeeded",
        bullet_lines=("ok",),
    )


def test_build_agent_events_respects_log_sequence() -> None:
    responses = (
        AgentResponse(
            text="step 1",
            display_text="step 1",
            timestamp=_build_timestamp("2025-01-01T12:00:05+00:00", source="test"),
            step_index=0,
            is_final=False,
        ),
    )
    final_response = AgentResponse(
        text="done",
        display_text="done",
        timestamp=_build_timestamp("2025-01-01T12:00:06+00:00", source="test"),
        step_index=None,
        is_final=True,
    )
    tool_calls = (
        ToolCallDetails(
            summary=_summary(),
            call_identifier="call-1",
            raw_data=None,
            timestamp=_build_timestamp("2025-01-01T12:00:02+00:00", source="test"),
            llm_request=None,
        ),
    )
    event_log = (
        AgentEvent(
            kind="agent_finished",
            occurred_at="2025-01-01T12:00:06+00:00",
            payload={"ok": True, "status": "succeeded", "result": "done"},
        ),
    )

    timeline = (
        AgentTimelineEntry(
            kind="tool_call",
            sequence=1,
            occurred_at="2025-01-01T12:00:02+00:00",
            call_id="call-1",
        ),
        AgentTimelineEntry(
            kind="llm_step",
            sequence=2,
            occurred_at="2025-01-01T12:00:05+00:00",
            step_index=0,
        ),
        AgentTimelineEntry(
            kind="agent_finished",
            sequence=3,
            occurred_at="2025-01-01T12:00:06+00:00",
        ),
    )

    events = _build_agent_events(
        responses, final_response, tool_calls, event_log, timeline=timeline
    )

    assert [event.kind for event in events] == ["tool", "response", "response"]
    assert [event.order_index for event in events] == [0, 1, 2]
    assert [event.sequence for event in events] == [1, 2, 3]
