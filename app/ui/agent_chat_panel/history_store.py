"""Persistence service for agent chat history collections."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Iterable

from ..chat_entry import ChatConversation
from .paths import _default_history_path, _normalize_history_path

logger = logging.getLogger(__name__)


class HistoryStore:
    """Manage loading and saving chat histories on disk."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = self._normalize(path)

    @staticmethod
    def _normalize(path: Path | str | None) -> Path:
        if path is None:
            return _default_history_path()
        return _normalize_history_path(path)

    @property
    def path(self) -> Path:
        """Return the active history path."""

        return self._path

    def set_path(
        self,
        path: Path | str | None,
        *,
        persist_existing: bool = False,
        conversations: Iterable[ChatConversation] | None = None,
        active_id: str | None = None,
    ) -> bool:
        """Update the history path if it changed."""

        new_path = self._normalize(path)
        if new_path == self._path:
            return False
        if persist_existing and conversations:
            try:
                self.save(conversations, active_id)
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Failed to persist conversations before switching history path")
        self._path = new_path
        return True

    def load(self) -> tuple[list[ChatConversation], str | None]:
        """Load conversations and the active conversation id."""

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return [], None
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Failed to load chat history from %s", self._path)
            return [], None

        if not isinstance(raw, Mapping):
            return [], None

        conversations_raw = raw.get("conversations")
        if not isinstance(conversations_raw, Sequence):
            return [], None

        conversations: list[ChatConversation] = []
        for item in conversations_raw:
            if not isinstance(item, Mapping):
                continue
            try:
                conversations.append(ChatConversation.from_dict(item))
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to deserialize stored conversation", exc_info=True)
                continue

        if not conversations:
            return [], None

        active_id = raw.get("active_id")
        if isinstance(active_id, str) and any(
            conv.conversation_id == active_id for conv in conversations
        ):
            return conversations, active_id
        return conversations, conversations[-1].conversation_id

    def save(
        self,
        conversations: Iterable[ChatConversation],
        active_id: str | None,
    ) -> None:
        """Persist *conversations* to the configured history path."""

        path = self._path
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 2,
            "active_id": active_id,
            "conversations": [conv.to_dict() for conv in conversations],
        }
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)


__all__ = ["HistoryStore"]
