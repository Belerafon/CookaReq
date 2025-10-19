from app.llm.tokenizer import TokenCountResult
from app.ui.agent_chat_panel.history import AgentChatHistory
from app.ui.chat_entry import ChatConversation, ChatEntry


def test_agent_chat_history_round_trip(tmp_path):
    history_path = tmp_path / "agent_chats.sqlite"
    events: list[tuple[str | None, str | None]] = []
    history = AgentChatHistory(
        history_path=history_path,
        on_active_changed=lambda previous, current: events.append((previous, current)),
    )

    conversation = ChatConversation.new()
    conversation.title = "Initial"
    history.set_conversations([conversation])
    history.set_active_id(conversation.conversation_id)
    history.save()

    assert history_path.exists()
    assert events == [(None, conversation.conversation_id)]

    loaded_events: list[tuple[str | None, str | None]] = []
    reloaded = AgentChatHistory(
        history_path=history_path,
        on_active_changed=lambda previous, current: loaded_events.append((previous, current)),
    )
    conversations, active_id = reloaded.load()

    assert len(conversations) == 1
    assert active_id == conversation.conversation_id
    assert loaded_events == [(None, conversation.conversation_id)]


def test_agent_chat_history_skips_clean_saves(monkeypatch, tmp_path):
    history = AgentChatHistory(history_path=tmp_path / "history.sqlite", on_active_changed=None)
    conversation = ChatConversation.new()
    history.set_conversations([conversation])
    history.set_active_id(conversation.conversation_id)

    calls: list[dict[str, object]] = []

    def _capture_save(conversations, active_id, *, dirty_ids=None, structure_dirty=False):  # type: ignore[unused-argument]
        calls.append(
            {
                "ids": {conv.conversation_id for conv in conversations},
                "dirty": set(dirty_ids or (conv.conversation_id for conv in conversations)),
                "structure": structure_dirty,
            }
        )

    monkeypatch.setattr(history._store, "save", _capture_save)

    history.save()
    assert len(calls) == 1
    assert calls[0]["dirty"] == {conversation.conversation_id}

    calls.clear()
    history.save()
    assert calls == []

    history.mark_conversation_dirty(conversation)
    history.save()

    assert len(calls) == 1
    assert calls[0]["dirty"] == {conversation.conversation_id}

    calls.clear()
    history.mark_structure_dirty()
    history.save()

    assert len(calls) == 1
    assert calls[0]["structure"] is True


def test_agent_chat_history_switch_path_persists_existing(tmp_path):
    original = tmp_path / "first.sqlite"
    history = AgentChatHistory(history_path=original, on_active_changed=None)
    initial = ChatConversation.new()
    history.set_conversations([initial])
    history.set_active_id(initial.conversation_id)
    history.save()

    new_conversation = ChatConversation.new()
    new_path = tmp_path / "second.sqlite"
    history.set_conversations([new_conversation])
    history.set_active_id(new_conversation.conversation_id)
    changed = history.set_path(new_path, persist_existing=True)

    assert changed is True
    history.save()
    assert new_path.exists()

    restored = AgentChatHistory(history_path=new_path, on_active_changed=None)
    conversations, active_id = restored.load()
    assert len(conversations) == 1
    assert active_id == new_conversation.conversation_id


def _conversation_with_entry(title: str) -> ChatConversation:
    conversation = ChatConversation.new()
    conversation.title = title
    entry = ChatEntry(
        prompt="Q",
        response="A",
        tokens=1,
        display_response="A",
        token_info=TokenCountResult.exact(1, model="cl100k_base"),
        prompt_at="2024-01-01T00:00:00Z",
        response_at="2024-01-01T00:05:00Z",
    )
    conversation.replace_entries([entry])
    return conversation


def test_has_persistable_conversations_ignores_draft_only_state(tmp_path):
    history = AgentChatHistory(history_path=tmp_path / "history.sqlite", on_active_changed=None)

    assert history.has_persistable_conversations() is False

    draft = ChatConversation.new()
    history.set_conversations([draft])

    assert history.has_persistable_conversations() is False

    populated = _conversation_with_entry("Stored")
    history.set_conversations([draft, populated])

    assert history.has_persistable_conversations() is True


def test_has_persistable_conversations_handles_lazy_entries(tmp_path):
    history = AgentChatHistory(history_path=tmp_path / "history.sqlite", on_active_changed=None)

    conversation = _conversation_with_entry("Lazy")
    snapshot = [ChatEntry.from_dict(entry.to_dict()) for entry in conversation.entries]
    conversation.mark_entries_unloaded(lambda: list(snapshot))

    assert conversation.entries_loaded is False

    history.set_conversations([conversation])

    assert history.has_persistable_conversations() is True


def test_switch_path_does_not_override_existing_target(tmp_path):
    original = tmp_path / "global.sqlite"
    history = AgentChatHistory(history_path=original, on_active_changed=None)
    draft = ChatConversation.new()
    history.set_conversations([draft])
    history.set_active_id(draft.conversation_id)

    target = tmp_path / "project.sqlite"
    target_history = AgentChatHistory(history_path=target, on_active_changed=None)
    existing = _conversation_with_entry("Existing")
    target_history.set_conversations([existing])
    target_history.set_active_id(existing.conversation_id)
    target_history.save()

    changed = history.set_path(target, persist_existing=True)

    assert changed is True

    conversations, active_id = history.load()
    assert len(conversations) == 1
    assert conversations[0].conversation_id == existing.conversation_id
    assert active_id == existing.conversation_id


def test_prune_empty_conversations_skips_materialisation(monkeypatch, tmp_path):
    history_path = tmp_path / "history.sqlite"
    seed = AgentChatHistory(history_path=history_path, on_active_changed=None)
    empty = ChatConversation.new()
    stored = _conversation_with_entry("Stored")
    seed.set_conversations([empty, stored])
    seed.set_active_id(empty.conversation_id)
    seed.save()

    history = AgentChatHistory(history_path=history_path, on_active_changed=None)
    conversations, _ = history.load()

    assert len(conversations) == 2
    loaded = history.get_conversation(stored.conversation_id)
    assert loaded is not None
    assert loaded.entries_loaded is False

    def _fail_load_entries(conversation_id):  # type: ignore[unused-argument]
        raise AssertionError("should not load entries")

    monkeypatch.setattr(history._store, "load_entries", _fail_load_entries)

    changed = history.prune_empty_conversations(verify_with_store=True)

    assert changed is True
    remaining = history.conversations
    assert len(remaining) == 1
    assert remaining[0].conversation_id == stored.conversation_id
    assert remaining[0].entries_loaded is False
