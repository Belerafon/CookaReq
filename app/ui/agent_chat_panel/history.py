"""State management helpers for agent chat history."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

import logging
import time

from ..chat_entry import ChatConversation
from .history_store import HistoryStore
from .debug_logging import emit_history_debug, elapsed_ns, get_history_logger


logger = get_history_logger("history")


class AgentChatHistory:
    """Encapsulate history persistence and active conversation tracking."""

    def __init__(
        self,
        *,
        history_path: Path | str | None,
        on_active_changed: Callable[[str | None, str | None], None] | None = None,
    ) -> None:
        self._store = HistoryStore(history_path)
        emit_history_debug(
            logger,
            "history.init",
            history_path=str(self._store.path),
        )
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
        debug_start_ns = (
            time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        )
        emit_history_debug(
            logger,
            "history.set_active_id.start",
            previous=previous,
            requested=conversation_id,
        )
        self._active_id = conversation_id
        if conversation_id is not None:
            conversation = self.get_conversation(conversation_id)
            if conversation is not None:
                self.ensure_conversation_entries(conversation)
            else:
                emit_history_debug(
                    logger,
                    "history.set_active_id.missing",
                    conversation_id=conversation_id,
                    known_ids=[conv.conversation_id for conv in self._conversations],
                )
        else:
            emit_history_debug(
                logger,
                "history.set_active_id.cleared",
            )
        if (
            self._on_active_changed is not None
            and previous != conversation_id
        ):
            self._on_active_changed(previous, conversation_id)
        emit_history_debug(
            logger,
            "history.set_active_id.completed",
            active_id=self._active_id,
            changed=previous != conversation_id,
            elapsed_ns=elapsed_ns(debug_start_ns),
        )

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
        debug_start_ns = time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        emit_history_debug(
            logger,
            "history.load.start",
            history_path=str(self._store.path),
        )
        conversations, active_id = self._store.load()
        emit_history_debug(
            logger,
            "history.load.store_payload",
            elapsed_ns=elapsed_ns(debug_start_ns),
            conversation_count=len(conversations),
            active_id=active_id,
        )
        self._conversations = list(conversations)
        self._active_id = active_id
        if active_id is not None:
            conversation = self.get_conversation(active_id)
            if conversation is not None:
                phase_ns = (
                    time.perf_counter_ns()
                    if logger.isEnabledFor(logging.DEBUG)
                    else None
                )
                self.ensure_conversation_entries(conversation)
                emit_history_debug(
                    logger,
                    "history.load.entries_loaded",
                    conversation_id=active_id,
                    elapsed_ns=elapsed_ns(phase_ns),
                )
        if self._on_active_changed is not None and previous != active_id:
            self._on_active_changed(previous, active_id)
        emit_history_debug(
            logger,
            "history.load.completed",
            elapsed_ns=elapsed_ns(debug_start_ns),
            conversation_count=len(self._conversations),
            active_id=self._active_id,
        )
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
        debug_start_ns = time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        emit_history_debug(
            logger,
            "history.set_path.start",
            path=path,
            persist_existing=persist_existing,
        )
        changed = self._store.set_path(
            path,
            persist_existing=persist_existing,
            conversations=conversations,
            active_id=self._active_id,
        )
        emit_history_debug(
            logger,
            "history.set_path.completed",
            changed=changed,
            history_path=str(self._store.path),
            elapsed_ns=elapsed_ns(debug_start_ns),
        )
        return changed

    # ------------------------------------------------------------------
    def ensure_conversation_entries(self, conversation: ChatConversation) -> None:
        """Ensure entries for *conversation* are available in memory."""

        if conversation.entries_loaded:
            emit_history_debug(
                logger,
                "history.ensure_entries.cached",
                conversation_id=conversation.conversation_id,
            )
            return
        debug_start_ns = time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        emit_history_debug(
            logger,
            "history.ensure_entries.load_start",
            conversation_id=conversation.conversation_id,
        )
        try:
            entries = self._store.load_entries(conversation.conversation_id)
        except Exception:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to load entries for agent chat conversation %s",
                conversation.conversation_id,
            )
            conversation.replace_entries(())
            emit_history_debug(
                logger,
                "history.ensure_entries.load_failed",
                conversation_id=conversation.conversation_id,
                elapsed_ns=elapsed_ns(debug_start_ns),
            )
        else:
            conversation.replace_entries(entries)
            emit_history_debug(
                logger,
                "history.ensure_entries.load_success",
                conversation_id=conversation.conversation_id,
                entry_count=len(entries),
                elapsed_ns=elapsed_ns(debug_start_ns),
            )


__all__ = ["AgentChatHistory"]

