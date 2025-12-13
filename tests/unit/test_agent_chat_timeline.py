from app.agent.run_contract import AgentEvent, AgentTimelineEntry, ToolResultSnapshot
from app.agent.timeline_utils import timeline_checksum
from app.ui.agent_chat_panel.view_model import ConversationTimelineCache, build_conversation_timeline
from app.ui.chat_entry import ChatConversation, ChatEntry


_DEF_TIMESTAMP = "2025-01-01T10:00:00+00:00"


def _conversation_with_entry(entry: ChatEntry) -> ChatConversation:
    conversation = ChatConversation.new()
    conversation.replace_entries([entry])
    return conversation


def _timeline_entries() -> tuple[AgentTimelineEntry, ...]:
    return (
        AgentTimelineEntry(
            kind="llm_step",
            sequence=0,
            occurred_at=_DEF_TIMESTAMP,
            step_index=1,
        ),
        AgentTimelineEntry(
            kind="tool_call",
            sequence=1,
            occurred_at="2025-01-01T10:00:01+00:00",
            call_id="call-1",
            status="succeeded",
        ),
        AgentTimelineEntry(
            kind="agent_finished",
            sequence=2,
            occurred_at="2025-01-01T10:00:02+00:00",
            status="succeeded",
        ),
    )


def _entry_with_timeline(
    timeline: tuple[AgentTimelineEntry, ...],
    *,
    tool_snapshots: tuple[ToolResultSnapshot, ...] | None = None,
) -> ChatEntry:
    checksum = timeline_checksum(timeline)
    snapshots = tool_snapshots or (
        ToolResultSnapshot(
            call_id="call-1",
            tool_name="alpha",
            status="succeeded",
            sequence=1,
            started_at="2025-01-01T10:00:01+00:00",
            completed_at="2025-01-01T10:00:02+00:00",
        ),
    )
    raw_result = {
        "ok": True,
        "status": "succeeded",
        "result_text": "All done",
        "events": {"events": []},
        "tool_results": [snapshot.to_dict() for snapshot in snapshots],
        "llm_trace": {
            "steps": [
                {
                    "index": 1,
                    "occurred_at": _DEF_TIMESTAMP,
                    "request": ({"role": "user", "content": "hello"},),
                    "response": {"content": "thinking"},
                }
            ]
        },
        "timeline": [entry.to_dict() for entry in timeline],
        "timeline_checksum": checksum,
    }
    return ChatEntry(
        prompt="Hello?",
        response="All done",
        display_response="All done",
        tokens=0,
        raw_result=raw_result,
        prompt_at=_DEF_TIMESTAMP,
        response_at=None,
    )


def test_conversation_timeline_prefers_payload_entries_over_diagnostic_rebuild() -> None:
    timeline = _timeline_entries()
    entry = _entry_with_timeline(timeline)
    entry.diagnostic = {
        "event_log": [
            AgentEvent(kind="agent_finished", occurred_at=_DEF_TIMESTAMP, payload={}).to_dict()
        ]
    }

    conversation_timeline = build_conversation_timeline(_conversation_with_entry(entry))
    turn = conversation_timeline.entries[0].agent_turn

    assert turn is not None
    assert turn.timeline_source == "payload"
    assert turn.timeline_is_authoritative is True
    assert [event.sequence for event in turn.events] == [0, 1, 2]
    assert [event.kind for event in turn.events] == ["response", "tool", "response"]


def test_timeline_cache_rebuilds_when_payload_checksum_changes() -> None:
    cache = ConversationTimelineCache()

    original_timeline = _timeline_entries()
    conversation = _conversation_with_entry(_entry_with_timeline(original_timeline))
    initial = cache.timeline_for(conversation)

    updated_timeline = original_timeline + (
        AgentTimelineEntry(
            kind="tool_call",
            sequence=3,
            occurred_at="2025-01-01T10:00:03+00:00",
            call_id="call-2",
            status="failed",
        ),
    )
    conversation.replace_entries(
        [
            _entry_with_timeline(
                updated_timeline,
                tool_snapshots=(
                    ToolResultSnapshot(
                        call_id="call-1",
                        tool_name="alpha",
                        status="succeeded",
                        sequence=1,
                        started_at="2025-01-01T10:00:01+00:00",
                        completed_at="2025-01-01T10:00:02+00:00",
                    ),
                    ToolResultSnapshot(
                        call_id="call-2",
                        tool_name="beta",
                        status="failed",
                        sequence=3,
                        started_at="2025-01-01T10:00:03+00:00",
                        completed_at="2025-01-01T10:00:04+00:00",
                    ),
                ),
            )
        ]
    )

    refreshed = cache.timeline_for(conversation)

    assert refreshed is not initial
    refreshed_turn = refreshed.entries[0].agent_turn
    assert refreshed_turn is not None
    assert [event.sequence for event in refreshed_turn.events] == [0, 1, 2, 3]


def test_timeline_cache_ignores_diagnostic_changes_for_cached_entries() -> None:
    cache = ConversationTimelineCache()

    timeline = _timeline_entries()
    entry = _entry_with_timeline(timeline)
    conversation = _conversation_with_entry(entry)

    cached = cache.timeline_for(conversation)

    entry.diagnostic = {
        "event_log": [
            AgentEvent(kind="llm_step", occurred_at=_DEF_TIMESTAMP, payload={"index": 1}).to_dict()
        ]
    }

    reused = cache.timeline_for(conversation)

    assert reused is cached
    assert reused.entries[0].agent_turn is cached.entries[0].agent_turn
    assert [event.sequence for event in reused.entries[0].agent_turn.events] == [0, 1, 2]
