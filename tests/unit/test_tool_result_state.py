from app.ui.agent_chat_panel.tool_result_state import StreamedToolResultState


def test_state_from_payload_builds_status_updates() -> None:
    payload = {
        "tool_call_id": "state-1",
        "agent_status": "running",
        "observed_at": "2025-10-03T08:00:00+00:00",
    }

    state = StreamedToolResultState.from_payload(payload)

    serialised = state.to_payload()
    updates = serialised.get("status_updates")
    assert isinstance(updates, list)
    assert updates
    assert updates[0]["status"] == "running"
    assert serialised.get("first_observed_at") == "2025-10-03T08:00:00+00:00"
    assert serialised.get("last_observed_at") == "2025-10-03T08:00:00+00:00"


def test_state_merge_payload_preserves_arguments() -> None:
    initial = {
        "tool_call_id": "state-2",
        "observed_at": "2025-10-03T08:10:00+00:00",
        "agent_status": "running",
        "arguments": {"path": "demo"},
    }

    update = {
        "tool_call_id": "state-2",
        "observed_at": "2025-10-03T08:11:00+00:00",
        "agent_status": "completed",
        "arguments": {"path": "demo", "mode": "sync"},
    }

    state = StreamedToolResultState.from_payload(initial)
    state.merge_payload(update)

    serialised = state.to_payload()
    assert serialised.get("arguments") == {"path": "demo", "mode": "sync"}
    assert serialised.get("completed_at") == "2025-10-03T08:11:00+00:00"
    assert serialised.get("last_observed_at") == "2025-10-03T08:11:00+00:00"
