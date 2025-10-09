"""Persistence service for agent chat history collections."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from .paths import _default_history_path, _normalize_history_path

if TYPE_CHECKING:
    from ..chat_entry import ChatConversation, ChatEntry


logger = logging.getLogger(__name__)


_SCHEMA_VERSION = 1


class HistoryStore:
    """Manage loading and saving chat histories on disk."""

    def __init__(self, path: Path | str | None = None) -> None:
        """Initialise store using *path* or the default persistent location."""
        self._path = self._normalize(path)

    # ------------------------------------------------------------------
    @staticmethod
    def _normalize(path: Path | str | None) -> Path:
        if path is None:
            return _default_history_path()
        return _normalize_history_path(path)

    # ------------------------------------------------------------------
    @property
    def path(self) -> Path:
        """Return the SQLite database path."""
        return self._path

    # ------------------------------------------------------------------
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
        if persist_existing and conversations is not None:
            conversation_list = list(conversations)
            for conversation in conversation_list:
                ensure_loaded = getattr(conversation, "ensure_entries_loaded", None)
                if callable(ensure_loaded):
                    try:
                        ensure_loaded()
                    except Exception:  # pragma: no cover - defensive logging
                        logger.exception(
                            "Failed to materialise entries before switching history path"
                        )
                        return False
            target_store = type(self)(new_path)
            try:
                target_store.save(conversation_list, active_id)
            except Exception:  # pragma: no cover - defensive logging
                logger.exception(
                    "Failed to persist conversations before switching history path"
                )
                return False
        self._path = new_path
        return True

    # ------------------------------------------------------------------
    def load(self) -> tuple[list[ChatConversation], str | None]:
        """Load conversations and the active conversation id."""
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                conversations = self._load_conversations(conn)
                if not conversations:
                    return [], None
                active_id = self._resolve_active_id(conn, conversations)
                return conversations, active_id
        except sqlite3.Error:  # pragma: no cover - defensive logging
            logger.exception("Failed to load chat history from %s", self._path)
            return [], None

    # ------------------------------------------------------------------
    def load_entries(self, conversation_id: str) -> list[ChatEntry]:
        """Return entries belonging to *conversation_id*."""
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                rows = conn.execute(
                    """
                    SELECT position, payload
                    FROM entries
                    WHERE conversation_id = ?
                    ORDER BY position
                    """,
                    (conversation_id,),
                ).fetchall()
        except sqlite3.Error:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to load chat entries for %s from %s",
                conversation_id,
                self._path,
            )
            return []

        entries: list[ChatEntry] = []
        from ..chat_entry import ChatEntry
        for row in rows:
            if isinstance(row, sqlite3.Row):
                position = row["position"]
                payload_raw = row["payload"]
            else:
                position, payload_raw = row
            if not isinstance(position, int):
                try:
                    position = int(position)
                except (TypeError, ValueError):
                    position = None

            if not isinstance(payload_raw, str):
                self._handle_corrupted_entry(
                    conversation_id,
                    position,
                    payload_raw,
                    detail="Stored payload is not a string.",
                )
                continue
            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensive logging
                self._handle_corrupted_entry(
                    conversation_id,
                    position,
                    payload_raw,
                    exc=exc,
                )
                continue
            if not isinstance(payload, dict):
                continue
            try:
                entries.append(ChatEntry.from_dict(payload))
            except Exception:  # pragma: no cover - defensive logging
                logger.exception(
                    "Failed to deserialize chat entry for %s",
                    conversation_id,
                )
        return entries

    # ------------------------------------------------------------------
    def save(
        self,
        conversations: Iterable[ChatConversation],
        active_id: str | None,
    ) -> None:
        """Persist *conversations* to the configured history path."""
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                with conn:
                    self._set_active_id(conn, active_id)
                    self._sync_conversations(conn, list(conversations))
        except sqlite3.Error:
            logger.exception("Failed to persist agent chat history to %s", self._path)
            raise

    # ------------------------------------------------------------------
    def save_active_id(self, active_id: str | None) -> None:
        """Persist only the active conversation id."""
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                with conn:
                    self._set_active_id(conn, active_id)
        except sqlite3.Error:
            logger.exception(
                "Failed to persist active chat selection to %s",
                self._path,
            )
            raise

    # ------------------------------------------------------------------
    def has_conversations(self) -> bool:
        """Return ``True`` when at least one conversation exists on disk."""
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                row = conn.execute(
                    "SELECT 1 FROM conversations LIMIT 1"
                ).fetchone()
        except sqlite3.Error:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to inspect chat history contents at %s", self._path
            )
            return False
        return row is not None

    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        path = self._path
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # ------------------------------------------------------------------
    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                position INTEGER NOT NULL,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                preview TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entries (
                conversation_id TEXT NOT NULL,
                position INTEGER NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (conversation_id, position),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
                    ON DELETE CASCADE
            )
            """
        )
        version = self._get_metadata(conn, "schema_version")
        if version is None:
            self._set_metadata(conn, "schema_version", str(_SCHEMA_VERSION))
        elif version != str(_SCHEMA_VERSION):
            raise sqlite3.DatabaseError(
                f"Unsupported chat history schema version: {version!r}"
            )

    # ------------------------------------------------------------------
    def _load_conversations(
        self, conn: sqlite3.Connection
    ) -> list[ChatConversation]:
        from ..chat_entry import ChatConversation
        rows = conn.execute(
            """
            SELECT id, title, created_at, updated_at, preview
            FROM conversations
            ORDER BY position
            """
        ).fetchall()
        conversations: list[ChatConversation] = []
        for row in rows:
            conversation = ChatConversation(
                conversation_id=row["id"],
                title=row["title"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                preview=row["preview"],
            )
            conversation.mark_entries_unloaded(
                lambda conv_id=row["id"]: self.load_entries(conv_id)
            )
            conversations.append(conversation)
        return conversations

    # ------------------------------------------------------------------
    def _resolve_active_id(
        self, conn: sqlite3.Connection, conversations: Sequence[ChatConversation]
    ) -> str | None:
        ids = [conv.conversation_id for conv in conversations]
        if not ids:
            return None
        active_id = self._get_metadata(conn, "active_id")
        if active_id in ids:
            return active_id
        return ids[-1]

    # ------------------------------------------------------------------
    def _sync_conversations(
        self, conn: sqlite3.Connection, conversations: list[ChatConversation]
    ) -> None:
        existing_ids = {
            row["id"]
            for row in conn.execute("SELECT id FROM conversations").fetchall()
        }
        desired_ids = {conv.conversation_id for conv in conversations}
        removed = existing_ids - desired_ids
        if removed:
            conn.executemany(
                "DELETE FROM conversations WHERE id = ?",
                ((conversation_id,) for conversation_id in removed),
            )

        for position, conversation in enumerate(conversations):
            preview = conversation.preview
            conn.execute(
                """
                INSERT INTO conversations (
                    id,
                    position,
                    title,
                    created_at,
                    updated_at,
                    preview
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    position = excluded.position,
                    title = excluded.title,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    preview = excluded.preview
                """,
                (
                    conversation.conversation_id,
                    position,
                    conversation.title,
                    conversation.created_at,
                    conversation.updated_at,
                    preview,
                ),
            )
            if conversation.entries_loaded:
                self._sync_entries(conn, conversation)

    # ------------------------------------------------------------------
    def _sync_entries(
        self, conn: sqlite3.Connection, conversation: ChatConversation
    ) -> None:
        rows = conn.execute(
            """
            SELECT position, payload
            FROM entries
            WHERE conversation_id = ?
            """,
            (conversation.conversation_id,),
        ).fetchall()

        existing_payloads: dict[int, str] = {}
        invalid_positions: list[object] = []

        for row in rows:
            raw_position = row["position"] if isinstance(row, sqlite3.Row) else row[0]
            payload_raw = row["payload"] if isinstance(row, sqlite3.Row) else row[1]

            try:
                position = int(raw_position)
            except (TypeError, ValueError):
                invalid_positions.append(raw_position)
                continue

            if position < 0 or not isinstance(payload_raw, str):
                invalid_positions.append(position)
                continue

            existing_payloads[position] = payload_raw

        if invalid_positions:
            payload = [
                (conversation.conversation_id, pos)
                for pos in invalid_positions
                if pos is not None
            ]
            if payload:
                conn.executemany(
                    "DELETE FROM entries WHERE conversation_id = ? AND position = ?",
                    payload,
                )

        seen_positions: set[int] = set()
        entries = conversation.entries
        for position, entry in enumerate(entries):
            payload = json.dumps(entry.to_dict(), ensure_ascii=False)
            current = existing_payloads.get(position)
            if current is None:
                conn.execute(
                    """
                    INSERT INTO entries (conversation_id, position, payload)
                    VALUES (?, ?, ?)
                    """,
                    (
                        conversation.conversation_id,
                        position,
                        payload,
                    ),
                )
            elif current != payload:
                conn.execute(
                    """
                    UPDATE entries
                    SET payload = ?
                    WHERE conversation_id = ? AND position = ?
                    """,
                    (
                        payload,
                        conversation.conversation_id,
                        position,
                    ),
                )
            seen_positions.add(position)

        stale_positions = [
            position for position in existing_payloads if position not in seen_positions
        ]
        if stale_positions:
            conn.executemany(
                "DELETE FROM entries WHERE conversation_id = ? AND position = ?",
                (
                    (conversation.conversation_id, position)
                    for position in stale_positions
                ),
            )

    # ------------------------------------------------------------------
    def _get_metadata(self, conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute(
            "SELECT value FROM metadata WHERE key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        value = row["value"]
        return value if isinstance(value, str) else None

    # ------------------------------------------------------------------
    def _set_metadata(self, conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            """
            INSERT INTO metadata (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

    # ------------------------------------------------------------------
    def _set_active_id(self, conn: sqlite3.Connection, active_id: str | None) -> None:
        if active_id is None:
            conn.execute("DELETE FROM metadata WHERE key = ?", ("active_id",))
        else:
            self._set_metadata(conn, "active_id", active_id)

    # ------------------------------------------------------------------
    def _handle_corrupted_entry(
        self,
        conversation_id: str,
        position: int | None,
        payload: object,
        *,
        detail: str | None = None,
        exc: Exception | None = None,
    ) -> None:
        """Log and prune an invalid entry payload."""
        snippet, payload_length = self._summarise_payload(payload)
        logger.error(
            (
                "Failed to decode stored chat entry for %s at position %s in %s. %s "
                "payload_length=%d, payload_preview=%r"
            ),
            conversation_id,
            "?" if position is None else position,
            self._path,
            detail or "Stored payload is not valid JSON.",
            payload_length,
            snippet,
            exc_info=exc,
        )
        if position is not None:
            self._delete_entry(conversation_id, position)

    # ------------------------------------------------------------------
    @staticmethod
    def _summarise_payload(payload: object, *, limit: int = 256) -> tuple[str, int]:
        """Return a short preview and size of *payload* for diagnostics."""
        if isinstance(payload, str):
            text = payload
            length = len(payload)
        elif isinstance(payload, bytes):
            text = payload.decode("utf-8", errors="replace")
            length = len(payload)
        else:
            text = repr(payload)
            length = len(text)
        snippet = text[:limit]
        if len(text) > limit:
            snippet = f"{snippet}… (truncated)"
        snippet = snippet.replace("\n", "\\n")
        return snippet, length

    # ------------------------------------------------------------------
    def _delete_entry(self, conversation_id: str, position: int) -> None:
        """Remove an invalid entry from the backing store."""
        try:
            with self._connect() as conn, conn:
                conn.execute(
                    "DELETE FROM entries WHERE conversation_id = ? AND position = ?",
                    (conversation_id, position),
                )
        except sqlite3.Error:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to prune corrupted entry %s/%s from %s",
                conversation_id,
                position,
                self._path,
            )


__all__ = ["HistoryStore"]
