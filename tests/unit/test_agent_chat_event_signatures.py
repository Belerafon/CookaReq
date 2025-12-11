from app.ui.agent_chat_panel.view_model import (
    AgentResponse,
    AgentTimelineEvent,
    TimestampInfo,
    ToolCallDetails,
    ToolCallSummary,
    agent_turn_event_signature,
)


def test_agent_turn_event_signature_changes_with_order_and_identity() -> None:
    timestamp = TimestampInfo(
        raw=None,
        occurred_at=None,
        formatted="",
        missing=True,
        source=None,
    )

    streamed = AgentResponse(
        text="step",
        display_text="step",
        timestamp=timestamp,
        step_index=1,
        is_final=False,
    )
    final = AgentResponse(
        text="done",
        display_text="done",
        timestamp=timestamp,
        step_index=2,
        is_final=True,
    )

    response_event = AgentTimelineEvent(
        kind="response",
        timestamp=timestamp,
        order_index=0,
        sequence=0,
        response=streamed,
    )
    final_event = AgentTimelineEvent(
        kind="response",
        timestamp=timestamp,
        order_index=2,
        sequence=2,
        response=final,
    )

    tool_summary = ToolCallSummary(
        index=1,
        tool_name="demo",
        status="ok",
        bullet_lines=(),
    )
    tool_call = ToolCallDetails(
        summary=tool_summary,
        call_identifier="call-1",
        raw_data=None,
        timestamp=timestamp,
    )
    tool_event = AgentTimelineEvent(
        kind="tool",
        timestamp=timestamp,
        order_index=1,
        sequence=1,
        tool_call=tool_call,
    )

    canonical_signature = agent_turn_event_signature(
        (response_event, tool_event, final_event)
    )
    swapped_signature = agent_turn_event_signature(
        (tool_event, response_event, final_event)
    )

    tool_call_moved = ToolCallDetails(
        summary=tool_summary,
        call_identifier="call-2",
        raw_data=None,
        timestamp=timestamp,
    )
    changed_identity_signature = agent_turn_event_signature(
        (
            AgentTimelineEvent(
                kind="tool",
                timestamp=timestamp,
                order_index=1,
                sequence=1,
                tool_call=tool_call_moved,
            ),
            response_event,
            final_event,
        )
    )

    assert canonical_signature != swapped_signature
    assert canonical_signature != changed_identity_signature
