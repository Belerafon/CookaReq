from app.agent.run_contract import AgentEvent, AgentEventLog, ToolResultSnapshot
from app.ui.agent_chat_panel.view_model import (
    ConversationTimelineCache,
    build_conversation_timeline,
)
from app.ui.chat_entry import ChatConversation, ChatEntry


def _conversation_with_entry(entry: ChatEntry) -> ChatConversation:
    conversation = ChatConversation.new()
    conversation._entries = [entry]
    return conversation


def test_agent_turn_reconstructs_timeline_from_event_log() -> None:
    event_log = AgentEventLog()
    event_log.append(
        AgentEvent(
            kind="llm_step",
            occurred_at="2025-01-01T10:00:00+00:00",
            payload={"index": 1},
        )
    )
    event_log.append(
        AgentEvent(
            kind="tool_started",
            occurred_at="2025-01-01T10:00:01+00:00",
            payload={"call_id": "call-1"},
        )
    )
    event_log.append(
        AgentEvent(
            kind="tool_completed",
            occurred_at="2025-01-01T10:00:02+00:00",
            payload={"call_id": "call-1"},
        )
    )
    event_log.append(
        AgentEvent(
            kind="agent_finished",
            occurred_at="2025-01-01T10:00:03+00:00",
            payload={},
        )
    )

    diagnostic = {
        "event_log": [event.to_dict() for event in event_log.events],
        "llm_steps": (
            {
                "step": 1,
                "occurred_at": "2025-01-01T10:00:00+00:00",
                "request": ({"role": "user", "content": "hello"},),
                "response": {"content": "thinking"},
            },
        ),
    }

    entry = ChatEntry(
        prompt="Hello?",
        response="All done",
        tokens=0,
        raw_result=None,
        prompt_at="2025-01-01T10:00:00+00:00",
        response_at=None,
    )
    entry.diagnostic = diagnostic
    entry.tool_results = (
        ToolResultSnapshot(
            call_id="call-1",
            tool_name="alpha",
            status="succeeded",
            sequence=1,
            started_at="2025-01-01T10:00:01+00:00",
            completed_at="2025-01-01T10:00:02+00:00",
        ).to_dict(),
    )

    timeline = build_conversation_timeline(_conversation_with_entry(entry))
    turn = timeline.entries[0].agent_turn

    assert turn is not None
    assert turn.timeline_is_authoritative is True
    assert turn.timeline_source == "event_log"
    assert [event.kind for event in turn.events] == ["response", "tool", "response"]
    assert [event.sequence for event in turn.events] == [0, 1, 3]
    assert [event.order_index for event in turn.events] == [0, 1, 3]


def test_timeline_cache_rebuilds_on_payload_change_without_invalidation() -> None:
    raw_result = {
        "result_text": "ok",
        "timeline": [
            {
                "kind": "llm_step",
                "sequence": 0,
                "step_index": 1,
                "occurred_at": "2025-03-01T10:00:00+00:00",
            },
            {
                "kind": "agent_finished",
                "sequence": 1,
                "occurred_at": "2025-03-01T10:00:04+00:00",
            },
        ],
        "events": {
            "events": [
                {
                    "kind": "llm_step",
                    "occurred_at": "2025-03-01T10:00:00+00:00",
                    "payload": {"index": 1},
                },
                {
                    "kind": "agent_finished",
                    "occurred_at": "2025-03-01T10:00:04+00:00",
                    "payload": {},
                },
            ]
        },
        "llm_trace": {
            "steps": [
                {
                    "index": 1,
                    "occurred_at": "2025-03-01T10:00:00+00:00",
                    "request": ({"role": "user", "content": "hello"},),
                    "response": {"content": "thinking"},
                }
            ]
        },
    }

    entry = ChatEntry(
        prompt="Hello?",
        response="All done",
        tokens=0,
        raw_result=raw_result,
        prompt_at="2025-03-01T10:00:00+00:00",
        response_at=None,
    )
    conversation = _conversation_with_entry(entry)
    cache = ConversationTimelineCache()

    initial_timeline = cache.timeline_for(conversation)
    initial_turn = initial_timeline.entries[0].agent_turn

    assert initial_turn is not None
    assert [event.kind for event in initial_turn.events] == ["response", "response"]
    assert [event.sequence for event in initial_turn.events] == [0, 1]

    entry.raw_result = {
        "result_text": "ok",
        "timeline": [
            {
                "kind": "llm_step",
                "sequence": 0,
                "step_index": 1,
                "occurred_at": "2025-03-01T10:00:00+00:00",
            },
            {
                "kind": "tool_call",
                "sequence": 1,
                "call_id": "call-1",
                "status": "succeeded",
                "occurred_at": "2025-03-01T10:00:02+00:00",
            },
            {
                "kind": "agent_finished",
                "sequence": 2,
                "occurred_at": "2025-03-01T10:00:04+00:00",
            },
        ],
        "events": {
            "events": [
                {
                    "kind": "llm_step",
                    "occurred_at": "2025-03-01T10:00:00+00:00",
                    "payload": {"index": 1},
                },
                {
                    "kind": "tool_started",
                    "occurred_at": "2025-03-01T10:00:01+00:00",
                    "payload": {"call_id": "call-1"},
                },
                {
                    "kind": "tool_completed",
                    "occurred_at": "2025-03-01T10:00:02+00:00",
                    "payload": {"call_id": "call-1"},
                },
                {
                    "kind": "agent_finished",
                    "occurred_at": "2025-03-01T10:00:04+00:00",
                    "payload": {},
                },
            ]
        },
        "tool_results": [
            ToolResultSnapshot(
                call_id="call-1",
                tool_name="alpha",
                status="succeeded",
                sequence=1,
                started_at="2025-03-01T10:00:01+00:00",
                completed_at="2025-03-01T10:00:02+00:00",
            ).to_dict()
        ],
        "llm_trace": {
            "steps": [
                {
                    "index": 1,
                    "occurred_at": "2025-03-01T10:00:00+00:00",
                    "request": ({"role": "user", "content": "hello"},),
                    "response": {"content": "thinking"},
                }
            ]
        },
    }

    updated_timeline = cache.timeline_for(conversation)
    updated_turn = updated_timeline.entries[0].agent_turn

    assert updated_turn is not None
    assert updated_turn.timeline_source in {"payload", "event_log"}
    assert [event.kind for event in updated_turn.events] == [
        "response",
        "tool",
        "response",
    ]
    sequences = [event.sequence for event in updated_turn.events]
    assert sequences[0] == 0
    assert sequences[0] < sequences[1] < sequences[2]


def test_agent_timeline_cache_detects_in_place_mutation() -> None:
    entry = ChatEntry(
        prompt="Hello?",
        response="All done",
        tokens=0,
        raw_result={
            "result_text": "ok",
            "timeline": [
                {
                    "kind": "llm_step",
                    "sequence": 0,
                    "step_index": 1,
                    "occurred_at": "2025-04-01T10:00:00+00:00",
                },
                {
                    "kind": "agent_finished",
                    "sequence": 1,
                    "occurred_at": "2025-04-01T10:00:04+00:00",
                },
            ],
            "events": {
                "events": [
                    {
                        "kind": "llm_step",
                        "occurred_at": "2025-04-01T10:00:00+00:00",
                        "payload": {"index": 1},
                    },
                    {
                        "kind": "agent_finished",
                        "occurred_at": "2025-04-01T10:00:04+00:00",
                        "payload": {},
                    },
                ]
            },
            "llm_trace": {
                "steps": [
                    {
                        "index": 1,
                        "occurred_at": "2025-04-01T10:00:00+00:00",
                        "request": ({"role": "user", "content": "hello"},),
                        "response": {"content": "thinking"},
                    }
                ]
            },
        },
        prompt_at="2025-04-01T10:00:00+00:00",
        response_at=None,
    )

    conversation = _conversation_with_entry(entry)
    raw_result = entry.raw_result
    assert isinstance(raw_result, dict)

    initial_turn = build_conversation_timeline(conversation).entries[0].agent_turn
    assert initial_turn is not None
    assert [event.kind for event in initial_turn.events] == ["response", "response"]
    assert [event.sequence for event in initial_turn.events] == [0, 1]

    raw_result["timeline"].insert(
        1,
        {
            "kind": "tool_call",
            "sequence": 1,
            "call_id": "call-1",
            "status": "succeeded",
            "occurred_at": "2025-04-01T10:00:02+00:00",
        },
    )
    raw_result["timeline"][2]["sequence"] = 2

    raw_result.setdefault("events", {}).setdefault("events", []).insert(
        1,
        {
            "kind": "tool_started",
            "occurred_at": "2025-04-01T10:00:01+00:00",
            "payload": {"call_id": "call-1"},
        },
    )
    raw_result["events"]["events"].insert(
        2,
        {
            "kind": "tool_completed",
            "occurred_at": "2025-04-01T10:00:02+00:00",
            "payload": {"call_id": "call-1"},
        },
    )

    raw_result["tool_results"] = [
        ToolResultSnapshot(
            call_id="call-1",
            tool_name="alpha",
            status="succeeded",
            sequence=1,
            started_at="2025-04-01T10:00:01+00:00",
            completed_at="2025-04-01T10:00:02+00:00",
        ).to_dict()
    ]

    updated_turn = build_conversation_timeline(conversation).entries[0].agent_turn

    assert updated_turn is not None
    assert [event.kind for event in updated_turn.events] == [
        "response",
        "tool",
        "response",
    ]
    assert [event.sequence for event in updated_turn.events] == [0, 1, 2]

def test_rebuilt_timeline_persisted_into_raw_result() -> None:
    raw_result = {
        "result_text": "ok",
        "timeline": [
            {
                "kind": "llm_step",
                "sequence": 0,
                "step_index": 1,
                "occurred_at": "2025-05-01T10:00:00+00:00",
            }
        ],
        "events": {
            "events": [
                {
                    "kind": "llm_step",
                    "occurred_at": "2025-05-01T10:00:00+00:00",
                    "payload": {"index": 1},
                },
                {
                    "kind": "agent_finished",
                    "occurred_at": "2025-05-01T10:00:02+00:00",
                    "payload": {},
                },
            ]
        },
        "llm_trace": {
            "steps": [
                {
                    "index": 1,
                    "occurred_at": "2025-05-01T10:00:00+00:00",
                    "request": ({"role": "user", "content": "hello"},),
                    "response": {"content": "thinking"},
                }
            ]
        },
    }

    entry = ChatEntry(
        prompt="Hello?",
        response="All done",
        tokens=0,
        raw_result=raw_result,
        prompt_at="2025-05-01T10:00:00+00:00",
        response_at=None,
    )

    timeline = build_conversation_timeline(_conversation_with_entry(entry))
    turn = timeline.entries[0].agent_turn

    assert turn is not None
    assert turn.timeline_source == "event_log"
    assert [event.sequence for event in turn.events] == [0, 1]

    stored_timeline = (
        entry.raw_result.get("timeline") if isinstance(entry.raw_result, dict) else None
    )
    assert isinstance(stored_timeline, list)
    assert [event.get("sequence") for event in stored_timeline] == [0, 1]
    assert stored_timeline[-1]["kind"] == "agent_finished"


def test_turn_timestamp_prefers_timeline_over_response_or_tools() -> None:
    raw_result = {
        "result_text": "ok",
        "timeline": [
            {
                "kind": "llm_step",
                "sequence": 0,
                "step_index": 1,
                "occurred_at": "2025-04-01T10:00:00+00:00",
            },
            {
                "kind": "tool_call",
                "sequence": 1,
                "call_id": "call-1",
                "status": "succeeded",
                "occurred_at": "2025-04-01T10:00:10+00:00",
            },
            {
                "kind": "agent_finished",
                "sequence": 2,
                "occurred_at": "2025-04-01T10:00:15+00:00",
            },
        ],
        "events": {"events": []},
        "llm_trace": {
            "steps": [
                {
                    "index": 1,
                    "occurred_at": "2025-04-01T10:00:00+00:00",
                    "response": {"content": "thinking"},
                }
            ]
        },
    }

    entry = ChatEntry(
        prompt="Hello?",
        response="All done",
        tokens=0,
        raw_result=raw_result,
        prompt_at="2025-04-01T09:59:59+00:00",
        response_at="2025-04-01T10:00:20+00:00",
    )
    entry.tool_results = (
        ToolResultSnapshot(
            call_id="call-1",
            tool_name="alpha",
            status="succeeded",
            sequence=1,
            started_at="2025-04-01T10:00:05+00:00",
            completed_at="2025-04-01T10:00:10+00:00",
        ).to_dict(),
    )

    timeline = build_conversation_timeline(_conversation_with_entry(entry))
    turn = timeline.entries[0].agent_turn

    assert turn is not None
    assert turn.timestamp.raw == "2025-04-01T10:00:15+00:00"
    assert turn.timestamp.source == "timeline"


def test_turn_timestamp_falls_back_to_llm_trace_when_timeline_is_missing() -> None:
    raw_result = {
        "result_text": "ok",
        "timeline": [
            {
                "kind": "llm_step",
                "sequence": 0,
                "step_index": 1,
                "occurred_at": None,
            },
            {
                "kind": "agent_finished",
                "sequence": 1,
                "occurred_at": None,
            },
        ],
        "events": {"events": []},
        "llm_trace": {
            "steps": [
                {
                    "index": 1,
                    "occurred_at": "2025-04-02T11:00:00+00:00",
                    "request": (),
                    "response": {"content": "done"},
                }
            ]
        },
    }

    entry = ChatEntry(
        prompt="Hello?",
        response="All done",
        tokens=0,
        raw_result=raw_result,
        prompt_at="2025-04-02T10:00:00+00:00",
        response_at=None,
    )

    timeline = build_conversation_timeline(_conversation_with_entry(entry))
    turn = timeline.entries[0].agent_turn

    assert turn is not None
    assert turn.timestamp.raw == "2025-04-02T11:00:00+00:00"
    assert turn.timestamp.source == "llm_trace"
