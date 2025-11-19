"""History synchronization helpers extracted from :mod:`panel`."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..chat_entry import ChatConversation
from .history import AgentChatHistory
from .session import AgentChatSession
from .view_model import ConversationTimelineCache


@dataclass(slots=True)
class HistorySyncResult:
    conversations: list[ChatConversation]
    active_id: str | None


class HistorySynchronizer:
    """Isolate history loading and cleanup logic for the chat panel."""

    def __init__(
        self,
        *,
        session: AgentChatSession,
        timeline_cache: ConversationTimelineCache,
        scheduler: Callable[[Callable[[], None]], None],
    ) -> None:
        self._session = session
        self._timeline_cache = timeline_cache
        self._scheduler = scheduler
        self._lazy_history_cleanup_pending = False

    @property
    def timeline_cache(self) -> ConversationTimelineCache:
        return self._timeline_cache

    # ------------------------------------------------------------------
    @property
    def history(self) -> AgentChatHistory:
        return self._session.history

    # ------------------------------------------------------------------
    def initialize(self) -> HistorySyncResult:
        history = self.history
        history.load()
        history.prune_empty_conversations()
        draft = ChatConversation.new()
        history.conversations.append(draft)
        history.set_active_id(draft.conversation_id)
        self._timeline_cache = ConversationTimelineCache()
        self._lazy_history_cleanup_pending = False
        self.schedule_lazy_history_cleanup()
        self._session.notify_history_changed()
        return HistorySyncResult(
            conversations=history.conversations,
            active_id=history.active_id,
        )

    # ------------------------------------------------------------------
    def schedule_lazy_history_cleanup(self) -> None:
        if self._lazy_history_cleanup_pending:
            return

        def _run_cleanup() -> None:
            self._lazy_history_cleanup_pending = False
            removed = self.history.prune_empty_conversations(verify_with_store=True)
            if removed:
                self._session.notify_history_changed()

        self._lazy_history_cleanup_pending = True
        self._scheduler(_run_cleanup)

    # ------------------------------------------------------------------
    def set_history_path(self, path: Path | str | None, *, persist_existing: bool) -> bool:
        changed = self._session.set_history_path(path, persist_existing=persist_existing)
        if changed:
            self._timeline_cache = ConversationTimelineCache()
        return changed

    # ------------------------------------------------------------------
    def remove_conversations(self, ids_to_remove: set[str]) -> None:
        if not ids_to_remove:
            return
        remaining = [
            conv
            for conv in self.history.conversations
            if conv.conversation_id not in ids_to_remove
        ]
        self.history.set_conversations(remaining)
        self.history.mark_structure_dirty()
        self.history.save()
        self._session.notify_history_changed()

    # ------------------------------------------------------------------
    def create_conversation(self, *, persist: bool) -> ChatConversation:
        conversation = ChatConversation.new()
        self.history.conversations.append(conversation)
        self.history.mark_conversation_dirty(conversation)
        if persist:
            self.history.save()
        self._session.notify_history_changed()
        return conversation

    # ------------------------------------------------------------------
    def ensure_active_conversation(self) -> ChatConversation:
        conversation_id = self.history.active_id
        if conversation_id:
            existing = self.history.get_conversation(conversation_id)
            if existing is not None:
                return existing
        return self.create_conversation(persist=False)

    # ------------------------------------------------------------------
    def set_active_conversation(self, conversation_id: str | None) -> None:
        self.history.set_active_id(conversation_id)

    # ------------------------------------------------------------------
    def refresh_timeline_cache(self) -> None:
        self._timeline_cache = ConversationTimelineCache()


__all__ = ["HistorySynchronizer", "HistorySyncResult"]
