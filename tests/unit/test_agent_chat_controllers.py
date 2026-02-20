from __future__ import annotations

from pathlib import Path

from app.ui.agent_chat_panel.history_sync import HistorySynchronizer
from app.ui.agent_chat_panel.session_controller import SessionConfig, SessionController
from app.ui.agent_chat_panel.view_model import ConversationTimelineCache
from app.ui.agent_chat_panel.history import AgentChatHistory
from app.ui.chat_entry import ChatConversation, ChatEntry
from app.ui.agent_chat_panel.token_usage import TOKEN_UNAVAILABLE_LABEL


class _FakeSession:
    def __init__(self, history: AgentChatHistory) -> None:
        self.history = history
        self.notifications: list[str] = []

    def notify_history_changed(self) -> None:
        self.notifications.append("history")

    def set_history_path(self, path: Path | str | None, *, persist_existing: bool) -> bool:
        return self.history.set_path(path, persist_existing=persist_existing)

    def save_history(self) -> None:
        self.history.save()


def test_history_sync_switches_active_and_prunes(tmp_path) -> None:
    history = AgentChatHistory(history_path=tmp_path / "history.json")
    session = _FakeSession(history)
    sync = HistorySynchronizer(
        session=session,
        timeline_cache=ConversationTimelineCache(),
        scheduler=lambda fn: fn(),
    )

    sync.initialize()
    original_id = history.active_id
    replacement = sync.create_conversation(persist=False)
    sync.set_active_conversation(replacement.conversation_id)

    sync.remove_conversations({original_id})

    assert history.active_id == replacement.conversation_id
    assert all(conv.conversation_id != original_id for conv in history.conversations)
    assert session.notifications  # notify called


def test_session_controller_normalizes_preferences_and_tokens() -> None:
    controller = SessionController(
        config=SessionConfig(
            token_model_resolver=lambda: None,
            context_window_resolver=lambda: 200,
        )
    )

    normalized = controller.normalize_confirm_preference("chat_only")
    assert normalized.name.lower() == "prompt"

    conversation = ChatConversation.new()
    entry = ChatEntry(
        prompt="Hello",
        response="World",
        tokens=0,
        display_response="World",
        raw_result=None,
        token_info=None,
        prompt_at="now",
        response_at="later",
        context_messages=None,
    )
    conversation.append_entry(entry)
    breakdown = controller.compute_context_token_breakdown(conversation)

    assert breakdown.total.tokens is not None and breakdown.total.tokens >= 0
    percentage = controller.format_context_percentage(breakdown.total)
    assert percentage != TOKEN_UNAVAILABLE_LABEL
