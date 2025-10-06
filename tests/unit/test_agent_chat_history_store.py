import logging
import sqlite3
from pathlib import Path

import pytest

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


def test_set_path_persists_existing_payload(tmp_path: Path, sample_conversation: ChatConversation) -> None:
    history_path = tmp_path / "agent_chats.sqlite"
    new_path = tmp_path / "new_history.sqlite"
    store = HistoryStore(history_path)
    store.save([sample_conversation], sample_conversation.conversation_id)

    changed = store.set_path(
        new_path,
        persist_existing=True,
        conversations=[sample_conversation],
        active_id=sample_conversation.conversation_id,
    )
    assert changed is True

    conversations, active_id = store.load()
    assert not conversations  # switched to empty database
    assert active_id is None

    store.save([sample_conversation], sample_conversation.conversation_id)

    new_store = HistoryStore(new_path)
    conversations, active_id = new_store.load()
    assert len(conversations) == 1
    assert active_id == sample_conversation.conversation_id

    reloaded = conversations[0]
    reloaded.ensure_entries_loaded()
    assert reloaded.entries[0].prompt == sample_conversation.entries[0].prompt


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
