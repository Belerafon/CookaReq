from app.ui.agent_chat_panel.history import AgentChatHistory
from app.ui.chat_entry import ChatConversation


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
