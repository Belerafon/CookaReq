"""State management helpers for agent chat history."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from collections.abc import Callable

import logging

from ..chat_entry import ChatConversation
from .history_store import HistoryStore


logger = logging.getLogger(__name__)


class AgentChatHistory:
    """Encapsulate history persistence and active conversation tracking."""

    def __init__(
        self,
        *,
        history_path: Path | str | None,
        on_active_changed: Callable[[str | None, str | None], None] | None = None,
    ) -> None:
        self._store = HistoryStore(history_path)
        self._conversations: list[ChatConversation] = []
        self._active_id: str | None = None
        self._on_active_changed = on_active_changed

    # ------------------------------------------------------------------
    @property
    def conversations(self) -> list[ChatConversation]:
        """Return the in-memory conversations."""
        return self._conversations

    # ------------------------------------------------------------------
    def get_conversation(self, conversation_id: str) -> ChatConversation | None:
        """Return conversation matching *conversation_id* when present."""
        for conversation in self._conversations:
            if conversation.conversation_id == conversation_id:
                return conversation
        return None

    # ------------------------------------------------------------------
    @property
    def active_id(self) -> str | None:
        """Return identifier of the currently selected conversation."""
        return self._active_id

    # ------------------------------------------------------------------
    @property
    def path(self) -> Path:
        """Expose backing store path so callers can surface it in the UI."""
        return self._store.path

    # ------------------------------------------------------------------
    def set_conversations(self, conversations: Sequence[ChatConversation]) -> None:
        """Replace the in-memory conversation list."""
        self._conversations = list(conversations)

    # ------------------------------------------------------------------
    def set_active_id(self, conversation_id: str | None) -> None:
        """Set active conversation id notifying listeners on change."""
        previous = self._active_id
        self._active_id = conversation_id
        if conversation_id is not None:
            conversation = self.get_conversation(conversation_id)
            if conversation is not None:
                self.ensure_conversation_entries(conversation)
        if (
            self._on_active_changed is not None
            and previous != conversation_id
        ):
            self._on_active_changed(previous, conversation_id)

    # ------------------------------------------------------------------
    def persist_active_selection(self) -> None:
        """Persist the currently selected conversation id."""
        try:
            self._store.save_active_id(self._active_id)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to persist active agent chat selection to %s",
                self._store.path,
            )

    # ------------------------------------------------------------------
    def load(self) -> tuple[list[ChatConversation], str | None]:
        """Populate memory state from disk and report the loaded payload."""
        previous = self._active_id
        conversations, active_id = self._store.load()
        self._conversations = list(conversations)
        self._active_id = active_id
        if active_id is not None:
            conversation = self.get_conversation(active_id)
            if conversation is not None:
                self.ensure_conversation_entries(conversation)
        if self._on_active_changed is not None and previous != active_id:
            self._on_active_changed(previous, active_id)
        return self._conversations, self._active_id

    # ------------------------------------------------------------------
    def save(self) -> None:
        """Persist current state to disk logging failures defensively."""
        try:
            self._store.save(self._conversations, self._active_id)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to persist agent chat history to %s", self._store.path
            )

    # ------------------------------------------------------------------
    def set_path(
        self,
        path: Path | str | None,
        *,
        persist_existing: bool = False,
    ) -> bool:
        """Switch history store to *path* returning ``True`` on change."""
        conversations: Iterable[ChatConversation] | None = (
            self._conversations if persist_existing else None
        )
        return self._store.set_path(
            path,
            persist_existing=persist_existing,
            conversations=conversations,
            active_id=self._active_id,
        )

    # ------------------------------------------------------------------
    def ensure_conversation_entries(self, conversation: ChatConversation) -> None:
        """Ensure entries for *conversation* are available in memory."""
        if conversation.entries_loaded:
            return
        try:
            entries = self._store.load_entries(conversation.conversation_id)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to load entries for agent chat conversation %s",
                conversation.conversation_id,
            )
            conversation.replace_entries(())
        else:
            conversation.replace_entries(entries)


__all__ = ["AgentChatHistory"]

