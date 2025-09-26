"""Persistence helpers for agent chat histories."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from ..chat_entry import ChatConversation


class HistoryPersistenceMixin:
    """Provide load/save helpers for chat history collections."""

    _history_path: Path
    _active_conversation_id: str | None
    conversations: list[ChatConversation]

    def _on_active_conversation_changed(
        self,
        previous_id: str | None,
        new_id: str | None,
    ) -> None:  # pragma: no cover - implemented by subclass
        raise NotImplementedError

    def _load_history(self) -> None:
        previous_id = getattr(self, "_active_conversation_id", None)
        self.conversations = []
        self._active_conversation_id = None
        self._on_active_conversation_changed(previous_id, self._active_conversation_id)
        try:
            raw = json.loads(self._history_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception:
            return

        if not isinstance(raw, Mapping):
            return

        conversations_raw = raw.get("conversations")
        if not isinstance(conversations_raw, Sequence):
            return

        conversations: list[ChatConversation] = []
        for item in conversations_raw:
            if isinstance(item, Mapping):
                try:
                    conversations.append(ChatConversation.from_dict(item))
                except Exception:  # pragma: no cover - defensive
                    continue
        if not conversations:
            return

        self.conversations = conversations
        active_id = raw.get("active_id")
        if isinstance(active_id, str) and any(
            conv.conversation_id == active_id for conv in self.conversations
        ):
            new_id = active_id
        else:
            new_id = self.conversations[-1].conversation_id
        previous_id = self._active_conversation_id
        self._active_conversation_id = new_id
        self._on_active_conversation_changed(previous_id, self._active_conversation_id)

    def _save_history(self) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 2,
            "active_id": self._active_conversation_id,
            "conversations": [conv.to_dict() for conv in self.conversations],
        }
        with self._history_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)


__all__ = ["HistoryPersistenceMixin"]
