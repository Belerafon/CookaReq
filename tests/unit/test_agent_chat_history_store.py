import json
import logging
import sqlite3
from pathlib import Path

import pytest

from app.agent.run_contract import AgentTimelineEntry
from app.agent.timeline_utils import timeline_checksum
from app.llm.tokenizer import TokenCountResult
from app.ui.agent_chat_panel.history_store import HistoryStore
from app.ui.chat_entry import ChatConversation, ChatEntry


@pytest.fixture()
def sample_conversation() -> ChatConversation:
    conversation = ChatConversation.new()
    conversation.title = "First"
    entry = ChatEntry(
        prompt="Question",
        response="Answer",
        tokens=1,
        display_response="Answer",
        raw_result=None,
        token_info=TokenCountResult.exact(1, model="cl100k_base"),
        prompt_at="2024-01-01T00:00:00Z",
        response_at="2024-01-01T00:05:00Z",
    )
    conversation.replace_entries([entry])
    conversation.updated_at = entry.response_at or entry.prompt_at or conversation.updated_at
    return conversation


def test_save_and_load_round_trip(tmp_path: Path, sample_conversation: ChatConversation) -> None:
    history_path = tmp_path / "agent_chats.sqlite"
    store = HistoryStore(history_path)
    secondary = ChatConversation.new()
    secondary.title = "Second"
    secondary_entry = ChatEntry.from_dict(sample_conversation.entries[0].to_dict())
    secondary.replace_entries([secondary_entry])
    secondary.updated_at = sample_conversation.updated_at

    store.save([sample_conversation, secondary], secondary.conversation_id)

    conversations, active_id = store.load()

    assert active_id == secondary.conversation_id
    assert len(conversations) == 2

    loaded = conversations[0]
    assert loaded.conversation_id == sample_conversation.conversation_id
    assert not loaded.entries  # lazy loaded
    assert not loaded.entries_loaded

    loaded.ensure_entries_loaded()

    assert loaded.entries_loaded
    assert len(loaded.entries) == 1
    assert loaded.preview == sample_conversation.preview


def test_save_active_id_updates_metadata_without_touching_entries(
    tmp_path: Path, sample_conversation: ChatConversation
) -> None:
    history_path = tmp_path / "agent_chats.sqlite"
    store = HistoryStore(history_path)
    store.save([sample_conversation], sample_conversation.conversation_id)

    before = store.load_entries(sample_conversation.conversation_id)
    store.save_active_id(sample_conversation.conversation_id)
    after = store.load_entries(sample_conversation.conversation_id)

    assert before[0].prompt == after[0].prompt

    conversations, active_id = store.load()
    assert len(conversations) == 1
    assert active_id == sample_conversation.conversation_id


def test_has_conversations_detects_existing_payload(
    tmp_path: Path, sample_conversation: ChatConversation
) -> None:
    history_path = tmp_path / "agent_chats.sqlite"
    store = HistoryStore(history_path)

    assert store.has_conversations() is False

    store.save([sample_conversation], sample_conversation.conversation_id)

    assert store.has_conversations() is True


def test_set_path_persists_existing_payload(
    tmp_path: Path, sample_conversation: ChatConversation
) -> None:
    history_path = tmp_path / "agent_chats.sqlite"
    new_path = tmp_path / "new_history.sqlite"
    store = HistoryStore(history_path)
    store.save([sample_conversation], sample_conversation.conversation_id)

    conversations, active_id = store.load()
    assert conversations
    snapshot = conversations[0]
    assert snapshot.conversation_id == sample_conversation.conversation_id
    assert not snapshot.entries_loaded  # loader should be deferred

    changed = store.set_path(
        new_path,
        persist_existing=True,
        conversations=conversations,
        active_id=active_id,
    )

    assert changed is True
    assert store.path == new_path
    assert new_path.exists()

    migrated_conversations, migrated_active = store.load()
    assert migrated_active == sample_conversation.conversation_id
    assert len(migrated_conversations) == 1

    migrated = migrated_conversations[0]
    assert migrated.conversation_id == sample_conversation.conversation_id
    assert not migrated.entries_loaded

    migrated_entries = store.load_entries(sample_conversation.conversation_id)
    assert len(migrated_entries) == 1
    assert migrated_entries[0].prompt == sample_conversation.entries[0].prompt


def _fetch_entry_rows(path: Path, conversation_id: str) -> list[sqlite3.Row]:
    with sqlite3.connect(str(path)) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT rowid, position, payload FROM entries WHERE conversation_id = ? ORDER BY position",
            (conversation_id,),
        ).fetchall()


def _clone_entry(entry: ChatEntry) -> ChatEntry:
    return ChatEntry.from_dict(entry.to_dict())


def test_sync_entries_appends_without_rewriting_existing_rows(
    tmp_path: Path, sample_conversation: ChatConversation
) -> None:
    history_path = tmp_path / "agent_chats.sqlite"
    store = HistoryStore(history_path)
    store.save([sample_conversation], sample_conversation.conversation_id)

    initial_rows = _fetch_entry_rows(history_path, sample_conversation.conversation_id)
    assert len(initial_rows) == 1
    initial_rowid = initial_rows[0]["rowid"]
    initial_payload = initial_rows[0]["payload"]

    second_entry = _clone_entry(sample_conversation.entries[0])
    second_entry.response = "Another answer"
    second_entry.display_response = "Another answer"
    second_entry.prompt_at = "2024-01-01T00:10:00Z"
    second_entry.response_at = "2024-01-01T00:15:00Z"
    sample_conversation.append_entry(second_entry)
    sample_conversation.updated_at = second_entry.response_at or sample_conversation.updated_at

    store.save([sample_conversation], sample_conversation.conversation_id)

    updated_rows = _fetch_entry_rows(history_path, sample_conversation.conversation_id)
    assert [row["position"] for row in updated_rows] == [0, 1]
    assert updated_rows[0]["rowid"] == initial_rowid
    assert updated_rows[0]["payload"] == initial_payload


def test_sync_entries_updates_in_place(tmp_path: Path, sample_conversation: ChatConversation) -> None:
    history_path = tmp_path / "agent_chats.sqlite"
    store = HistoryStore(history_path)
    store.save([sample_conversation], sample_conversation.conversation_id)

    original_rows = _fetch_entry_rows(history_path, sample_conversation.conversation_id)
    original_rowid = original_rows[0]["rowid"]

    sample_conversation.entries[0].response = "Edited"
    sample_conversation.entries[0].display_response = "Edited"
    sample_conversation.updated_at = "2024-01-01T00:20:00Z"

    store.save([sample_conversation], sample_conversation.conversation_id)

    rewritten_rows = _fetch_entry_rows(history_path, sample_conversation.conversation_id)
    assert len(rewritten_rows) == 1
    assert rewritten_rows[0]["rowid"] == original_rowid
    assert rewritten_rows[0]["payload"] != original_rows[0]["payload"]


def test_sync_entries_removes_stale_rows(tmp_path: Path) -> None:
    history_path = tmp_path / "agent_chats.sqlite"
    store = HistoryStore(history_path)

    conversation = ChatConversation.new()
    conversation.title = "History"
    first_entry = ChatEntry(
        prompt="Q1",
        response="A1",
        tokens=1,
        display_response="A1",
        prompt_at="2024-01-01T00:00:00Z",
        response_at="2024-01-01T00:01:00Z",
        token_info=TokenCountResult.exact(1, model="cl100k_base"),
    )
    second_entry = ChatEntry(
        prompt="Q2",
        response="A2",
        tokens=1,
        display_response="A2",
        prompt_at="2024-01-01T00:02:00Z",
        response_at="2024-01-01T00:03:00Z",
        token_info=TokenCountResult.exact(1, model="cl100k_base"),
    )
    conversation.replace_entries([first_entry, second_entry])
    conversation.updated_at = second_entry.response_at or conversation.updated_at

    store.save([conversation], conversation.conversation_id)

    rows_before = _fetch_entry_rows(history_path, conversation.conversation_id)
    assert len(rows_before) == 2
    first_rowid = rows_before[0]["rowid"]

    conversation.replace_entries([first_entry])
    conversation.updated_at = "2024-01-01T00:04:00Z"

    store.save([conversation], conversation.conversation_id)

    rows_after = _fetch_entry_rows(history_path, conversation.conversation_id)
    assert len(rows_after) == 1
    assert rows_after[0]["rowid"] == first_rowid


def test_save_with_dirty_ids_skips_clean_conversations(
    tmp_path: Path, sample_conversation: ChatConversation
) -> None:
    history_path = tmp_path / "agent.sqlite"
    store = HistoryStore(history_path)

    secondary = ChatConversation.new()
    secondary.title = "Second"
    secondary_entry = ChatEntry.from_dict(sample_conversation.entries[0].to_dict())
    secondary.replace_entries([secondary_entry])
    secondary.updated_at = secondary_entry.response_at or secondary.updated_at

    store.save(
        [sample_conversation, secondary],
        secondary.conversation_id,
    )

    sample_conversation.entries[0].response = "Edited"
    sample_conversation.entries[0].display_response = "Edited"
    sample_conversation.updated_at = "2024-01-01T00:10:00Z"

    calls: list[str] = []
    original_sync_entries = store._sync_entries

    def _record_sync(conn, conversation):  # type: ignore[no-untyped-def]
        calls.append(conversation.conversation_id)
        return original_sync_entries(conn, conversation)

    store._sync_entries = _record_sync  # type: ignore[assignment]
    try:
        store.save(
            [sample_conversation, secondary],
            secondary.conversation_id,
            dirty_ids={sample_conversation.conversation_id},
        )
    finally:
        store._sync_entries = original_sync_entries  # type: ignore[assignment]

    assert calls == [sample_conversation.conversation_id]


def test_load_entries_prunes_corrupted_payload(
    tmp_path: Path, sample_conversation: ChatConversation, caplog: pytest.LogCaptureFixture
) -> None:
    history_path = tmp_path / "agent_chats.sqlite"
    store = HistoryStore(history_path)
    store.save([sample_conversation], sample_conversation.conversation_id)

    with sqlite3.connect(str(history_path)) as conn:
        conn.execute(
            "UPDATE entries SET payload = ? WHERE conversation_id = ?",
            ("{", sample_conversation.conversation_id),
        )
        conn.commit()

    caplog.set_level(logging.ERROR)

    entries = store.load_entries(sample_conversation.conversation_id)

    assert entries == []

    with sqlite3.connect(str(history_path)) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE conversation_id = ?",
            (sample_conversation.conversation_id,),
        ).fetchone()[0]
    assert remaining == 0

    messages = [
        record.getMessage()
        for record in caplog.records
        if "Failed to decode stored chat entry" in record.getMessage()
    ]
    assert messages, "expected error log for corrupted payload"
    message = messages[0]
    assert str(sample_conversation.conversation_id) in message
    assert "payload_length" in message
    assert "payload_preview" in message


def test_load_entries_migrates_timeline_metadata(tmp_path: Path) -> None:
    history_path = tmp_path / "agent_chats.sqlite"
    store = HistoryStore(history_path)

    conversation = ChatConversation.new()
    conversation.title = "Legacy"
    entry = ChatEntry(
        prompt="Legacy?",
        response="Legacy!",
        tokens=1,
        display_response="Legacy!",
        raw_result=None,
        token_info=TokenCountResult.exact(1, model="cl100k_base"),
        prompt_at="2024-01-01T00:00:00Z",
        response_at="2024-01-01T00:01:00Z",
    )
    conversation.replace_entries([entry])
    conversation.updated_at = entry.response_at or conversation.updated_at
    store.save([conversation], conversation.conversation_id)

    timeline = [
        AgentTimelineEntry(
            kind="llm_step",
            occurred_at="2024-01-01T00:00:01Z",
            sequence=1,
            step_index=1,
        ),
        AgentTimelineEntry(
            kind="agent_finished",
            occurred_at="2024-01-01T00:00:02Z",
            sequence=2,
            status="succeeded",
        ),
    ]
    legacy_payload = conversation.entries[0].to_dict()
    legacy_payload.pop("timeline_status", None)
    legacy_payload.pop("timeline_checksum", None)
    legacy_payload["raw_result"] = {
        "ok": True,
        "status": "succeeded",
        "result": legacy_payload["response"],
        "events": {"events": []},
        "llm_trace": {"steps": []},
        "tool_results": [],
        "timeline": [entry.to_dict() for entry in timeline],
        "diagnostic": {"event_log": [{"kind": "llm_step", "sequence": 1}]},
    }
    legacy_payload["diagnostic"] = {"event_log": [{"kind": "llm_step", "sequence": 1}]}

    with sqlite3.connect(str(history_path)) as conn:
        conn.execute(
            "UPDATE entries SET payload = ? WHERE conversation_id = ? AND position = ?",
            (
                json.dumps(legacy_payload, ensure_ascii=False),
                conversation.conversation_id,
                0,
            ),
        )

    migrated_entries = store.load_entries(conversation.conversation_id)
    assert migrated_entries
    migrated = migrated_entries[0]
    expected_checksum = timeline_checksum(timeline)

    assert migrated.timeline_status == "valid"
    assert migrated.timeline_checksum == expected_checksum
    assert migrated.diagnostic is None or "event_log" not in migrated.diagnostic

    raw_result = migrated.raw_result if isinstance(migrated.raw_result, dict) else {}
    assert "event_log" not in (raw_result.get("diagnostic") or {})

    rows_after = _fetch_entry_rows(history_path, conversation.conversation_id)
    stored_payload = json.loads(rows_after[0]["payload"])
    assert stored_payload["timeline_status"] == "valid"
    assert stored_payload.get("timeline_checksum") == expected_checksum
    assert "event_log" not in (stored_payload.get("diagnostic") or {})
    assert "event_log" not in (
        (stored_payload.get("raw_result") or {}).get("diagnostic") or {}
    )
