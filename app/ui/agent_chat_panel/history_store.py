"""Persistence service for agent chat history collections."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from ..chat_entry import ChatConversation
from .paths import _default_history_path, _normalize_history_path


logger = logging.getLogger(__name__)


def _temporary_path(path: Path) -> Path:
    """Return a deterministic temporary path next to *path*."""

    suffix = path.suffix
    if suffix:
        return path.with_suffix(f"{suffix}.tmp")
    return path.with_name(f"{path.name}.tmp")


class HistoryStore:
    """Manage loading and saving chat histories on disk."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = self._normalize(path)
        self._active_path = self._derive_active_path(self._path)
        self._cached_payload: dict[str, Any] | None = None

    @staticmethod
    def _normalize(path: Path | str | None) -> Path:
        if path is None:
            return _default_history_path()
        return _normalize_history_path(path)

    @staticmethod
    def _derive_active_path(path: Path) -> Path:
        if path.suffix:
            return path.with_name(f"{path.stem}_active{path.suffix}")
        return path.with_name(f"{path.name}_active")

    @property
    def path(self) -> Path:
        """Return the active history path."""

        return self._path

    @property
    def active_path(self) -> Path:
        """Return the path used to persist the active conversation id."""

        return self._active_path

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
                logger.exception(
                    "Failed to persist conversations before switching history path"
                )
        self._path = new_path
        self._active_path = self._derive_active_path(new_path)
        self._cached_payload = None
        return True

    def load(self) -> tuple[list[ChatConversation], str | None]:
        """Load conversations and the active conversation id."""

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._cached_payload = None
            self._remove_active_override()
            return [], None
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Failed to load chat history from %s", self._path)
            self._cached_payload = None
            return [], None

        if not isinstance(raw, Mapping):
            self._cached_payload = None
            return [], None

        version = raw.get("version")
        if not isinstance(version, int) or version != 2:
            logger.warning(
                "Unsupported chat history version in %s: %r", self._path, version
            )
            self._cached_payload = None
            return [], None

        conversations_raw = raw.get("conversations")
        if not isinstance(conversations_raw, Sequence):
            self._cached_payload = None
            return [], None

        conversations: list[ChatConversation] = []
        for item in conversations_raw:
            if not isinstance(item, Mapping):
                continue
            try:
                conversation = ChatConversation.from_dict(item)
            except Exception:  # pragma: no cover - defensive
                logger.exception("Failed to deserialize stored conversation")
                continue
            entries_raw = item.get("entries")
            had_entries = isinstance(entries_raw, Sequence) and bool(entries_raw)
            if had_entries and not conversation.entries:
                logger.warning(
                    "Skipping chat conversation %s with no valid entries",
                    conversation.conversation_id,
                )
                continue
            conversations.append(conversation)

        if not conversations:
            self._cached_payload = None
            self._remove_active_override()
            return [], None

        active_id = raw.get("active_id")
        conversation_ids = {conv.conversation_id for conv in conversations}
        if isinstance(active_id, str) and active_id in conversation_ids:
            selected_id = active_id
        else:
            selected_id = conversations[-1].conversation_id

        override = self._load_active_override(conversation_ids)
        if override is not None:
            selected_id = override

        self._cached_payload = self._serialize_state(conversations, selected_id)
        return conversations, selected_id

    def save(
        self,
        conversations: Iterable[ChatConversation],
        active_id: str | None,
    ) -> None:
        """Persist *conversations* to the configured history path."""

        payload = self._serialize_state(conversations, active_id)
        self._write_payload(payload)
        self._cached_payload = payload
        self._write_active_override(active_id)

    def save_active_id(self, active_id: str | None) -> None:
        """Persist only the active conversation id."""

        if self._cached_payload is not None:
            cached = dict(self._cached_payload)
            cached["active_id"] = active_id
            self._cached_payload = cached
        self._write_active_override(active_id)

    # ------------------------------------------------------------------
    def _serialize_state(
        self,
        conversations: Iterable[ChatConversation],
        active_id: str | None,
    ) -> dict[str, Any]:
        return {
            "version": 2,
            "active_id": active_id,
            "conversations": [conv.to_dict() for conv in conversations],
        }

    def _write_payload(self, payload: Mapping[str, Any]) -> None:
        path = self._path
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = _temporary_path(path)
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def _load_active_override(self, conversation_ids: set[str]) -> str | None:
        try:
            raw = json.loads(self._active_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except Exception:  # pragma: no cover - defensive logging
            logger.warning("Failed to load active chat id from %s", self._active_path)
            return None
        candidate = raw.get("active_id") if isinstance(raw, Mapping) else None
        if isinstance(candidate, str) and candidate in conversation_ids:
            return candidate
        return None

    def _write_active_override(self, active_id: str | None) -> None:
        path = self._active_path
        if active_id is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"active_id": active_id}
        tmp_path = _temporary_path(path)
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(path)

    def _remove_active_override(self) -> None:
        try:
            self._active_path.unlink()
        except FileNotFoundError:
            pass


__all__ = ["HistoryStore"]
