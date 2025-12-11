from types import SimpleNamespace

from app.ui.agent_chat_panel.segment_view import (
    _ConversationRenderCache,
    _detect_dirty_entries,
)
from app.ui.agent_chat_panel.view_model import (
    AgentResponse,
    AgentTimelineEvent,
    AgentTurn,
    TimestampInfo,
    TranscriptEntry,
    agent_turn_event_signature,
)


def _build_timeline_entry(entry_id: str, *, reversed_order: bool) -> TranscriptEntry:
    timestamp = TimestampInfo(
        raw=None,
        occurred_at=None,
        formatted="",
        missing=True,
        source=None,
    )
    response = AgentResponse(
        text="hello",
        display_text="hello",
        timestamp=timestamp,
        step_index=1,
        is_final=True,
        regenerated=False,
    )

    response_event = AgentTimelineEvent(
        kind="response",
        timestamp=timestamp,
        order_index=0,
        sequence=0,
        response=response,
    )
    tool_event = AgentTimelineEvent(
        kind="tool",
        timestamp=timestamp,
        order_index=1,
        sequence=1,
        tool_call=None,
    )

    events = (tool_event, response_event) if reversed_order else (response_event, tool_event)

    turn = AgentTurn(
        entry_id=entry_id,
        entry_index=0,
        occurred_at=None,
        timestamp=timestamp,
        streamed_responses=(response,),
        final_response=response,
        reasoning=(),
        reasoning_by_step={},
        llm_request=None,
        tool_calls=(),
        raw_payload=None,
        events=events,
        event_signature=agent_turn_event_signature(events),
    )

    return TranscriptEntry(
        entry_id=entry_id,
        entry_index=0,
        entry=SimpleNamespace(layout_hints={}),
        prompt=None,
        context_messages=(),
        agent_turn=turn,
        system_messages=(),
        layout_hints={},
        can_regenerate=False,
    )


def test_detect_dirty_entries_flags_signature_change_without_explicit_ids() -> None:
    entry_id = "c:0"
    cache = _ConversationRenderCache()
    initial_entry = _build_timeline_entry(entry_id, reversed_order=False)
    cache.entry_snapshots[entry_id] = initial_entry
    cache.entry_signatures[entry_id] = initial_entry.agent_turn.event_signature

    initial_lookup = {entry_id: initial_entry}
    initial_dirty = _detect_dirty_entries(
        cache, initial_lookup, None, entry_order=[entry_id]
    )
    assert initial_dirty == []

    reordered_entry = _build_timeline_entry(entry_id, reversed_order=True)
    reordered_lookup = {entry_id: reordered_entry}
    reordered_dirty = _detect_dirty_entries(
        cache, reordered_lookup, None, entry_order=[entry_id]
    )

    assert reordered_dirty == [entry_id]
