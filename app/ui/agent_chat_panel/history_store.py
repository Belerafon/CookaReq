"""Persistence service for agent chat history collections."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Iterable, Sequence
from pathlib import Path

from ..chat_entry import ChatConversation, ChatEntry
from .debug_logging import emit_history_debug, elapsed_ns
from .paths import _default_history_path, _normalize_history_path


logger = logging.getLogger(__name__)


_SCHEMA_VERSION = 1


class HistoryStore:
    """Manage loading and saving chat histories on disk."""

    def __init__(self, path: Path | str | None = None) -> None:
        self._path = self._normalize(path)
        emit_history_debug(
            logger,
            "store.init",
            history_path=str(self._path),
        )

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
        emit_history_debug(
            logger,
            "store.set_path.start",
            requested_path=path,
            normalized=str(new_path),
            persist_existing=persist_existing,
        )
        if new_path == self._path:
            emit_history_debug(
                logger,
                "store.set_path.no_change",
                history_path=str(self._path),
            )
            return False
        if persist_existing and conversations is not None:
            phase_ns = time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
            try:
                self.save(conversations, active_id)
            except Exception:  # pragma: no cover - defensive logging
                logger.exception(
                    "Failed to persist conversations before switching history path"
                )
                emit_history_debug(
                    logger,
                    "store.set_path.persist_failed",
                    history_path=str(self._path),
                    elapsed_ns=elapsed_ns(phase_ns),
                )
            self._path = new_path
            emit_history_debug(
                logger,
                "store.set_path.persist_completed",
                history_path=str(self._path),
                elapsed_ns=elapsed_ns(phase_ns),
            )
        else:
            self._path = new_path
        emit_history_debug(
            logger,
            "store.set_path.changed",
            history_path=str(self._path),
        )
        return True

    # ------------------------------------------------------------------
    def load(self) -> tuple[list[ChatConversation], str | None]:
        """Load conversations and the active conversation id."""

        debug_start_ns = time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        emit_history_debug(
            logger,
            "store.load.start",
            history_path=str(self._path),
        )
        try:
            with self._connect() as conn:
                emit_history_debug(
                    logger,
                    "store.load.connected",
                    elapsed_ns=elapsed_ns(debug_start_ns),
                )
                self._ensure_schema(conn)
                emit_history_debug(
                    logger,
                    "store.load.schema_ready",
                    elapsed_ns=elapsed_ns(debug_start_ns),
                )
                conversations = self._load_conversations(conn)
                emit_history_debug(
                    logger,
                    "store.load.conversations",
                    elapsed_ns=elapsed_ns(debug_start_ns),
                    conversation_count=len(conversations),
                )
                if not conversations:
                    emit_history_debug(
                        logger,
                        "store.load.no_conversations",
                        elapsed_ns=elapsed_ns(debug_start_ns),
                    )
                    return [], None
                active_id = self._resolve_active_id(conn, conversations)
                emit_history_debug(
                    logger,
                    "store.load.active_id",
                    elapsed_ns=elapsed_ns(debug_start_ns),
                    active_id=active_id,
                )
                return conversations, active_id
        except sqlite3.Error:  # pragma: no cover - defensive logging
            logger.exception("Failed to load chat history from %s", self._path)
            emit_history_debug(
                logger,
                "store.load.error",
                elapsed_ns=elapsed_ns(debug_start_ns),
            )
            return [], None

    # ------------------------------------------------------------------
    def load_entries(self, conversation_id: str) -> list[ChatEntry]:
        """Return entries belonging to *conversation_id*."""

        debug_start_ns = time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        emit_history_debug(
            logger,
            "store.load_entries.start",
            history_path=str(self._path),
            conversation_id=conversation_id,
        )
        try:
            with self._connect() as conn:
                self._ensure_schema(conn)
                emit_history_debug(
                    logger,
                    "store.load_entries.schema_ready",
                    elapsed_ns=elapsed_ns(debug_start_ns),
                )
                rows = conn.execute(
                    """
                    SELECT payload
                    FROM entries
                    WHERE conversation_id = ?
                    ORDER BY position
                    """,
                    (conversation_id,),
                ).fetchall()
        except sqlite3.Error:  # pragma: no cover - defensive logging
            logger.exception(
                "Failed to load chat entries for %s from %s", conversation_id, self._path
            )
            emit_history_debug(
                logger,
                "store.load_entries.error",
                elapsed_ns=elapsed_ns(debug_start_ns),
            )
            return []

        entries: list[ChatEntry] = []
        for row in rows:
            payload_raw = row["payload"]
            if not isinstance(payload_raw, str):
                continue
            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError:  # pragma: no cover - defensive logging
                logger.exception("Failed to decode stored chat entry for %s", conversation_id)
                continue
            if not isinstance(payload, dict):
                continue
            try:
                entries.append(ChatEntry.from_dict(payload))
            except Exception:  # pragma: no cover - defensive logging
                logger.exception("Failed to deserialize chat entry for %s", conversation_id)
        emit_history_debug(
            logger,
            "store.load_entries.completed",
            conversation_id=conversation_id,
            entry_count=len(entries),
            elapsed_ns=elapsed_ns(debug_start_ns),
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
            logger.exception("Failed to persist active chat selection to %s", self._path)
            raise

    # ------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        debug_start_ns = time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        path = self._path
        emit_history_debug(
            logger,
            "store.connect.start",
            history_path=str(path),
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        emit_history_debug(
            logger,
            "store.connect.ready",
            history_path=str(path),
            elapsed_ns=elapsed_ns(debug_start_ns),
        )
        return conn

    # ------------------------------------------------------------------
    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        debug_start_ns = time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        emit_history_debug(
            logger,
            "store.ensure_schema.start",
            history_path=str(self._path),
        )
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
        emit_history_debug(
            logger,
            "store.ensure_schema.completed",
            elapsed_ns=elapsed_ns(debug_start_ns),
            schema_version=str(version) if version is not None else str(_SCHEMA_VERSION),
        )

    # ------------------------------------------------------------------
    def _load_conversations(
        self, conn: sqlite3.Connection
    ) -> list[ChatConversation]:
        debug_start_ns = time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        emit_history_debug(
            logger,
            "store.load_conversations.start",
        )
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
        emit_history_debug(
            logger,
            "store.load_conversations.completed",
            elapsed_ns=elapsed_ns(debug_start_ns),
            conversation_count=len(conversations),
        )
        return conversations

    # ------------------------------------------------------------------
    def _resolve_active_id(
        self, conn: sqlite3.Connection, conversations: Sequence[ChatConversation]
    ) -> str | None:
        ids = [conv.conversation_id for conv in conversations]
        if not ids:
            return None
        debug_start_ns = time.perf_counter_ns() if logger.isEnabledFor(logging.DEBUG) else None
        emit_history_debug(
            logger,
            "store.resolve_active_id.start",
            candidate_count=len(ids),
        )
        active_id = self._get_metadata(conn, "active_id")
        if active_id in ids:
            emit_history_debug(
                logger,
                "store.resolve_active_id.existing",
                active_id=active_id,
                elapsed_ns=elapsed_ns(debug_start_ns),
            )
            return active_id
        fallback = ids[-1]
        emit_history_debug(
            logger,
            "store.resolve_active_id.fallback",
            active_id=fallback,
            elapsed_ns=elapsed_ns(debug_start_ns),
        )
        return fallback

    # ------------------------------------------------------------------
    def _sync_conversations(
        self, conn: sqlite3.Connection, conversations: list[ChatConversation]
    ) -> None:
        existing_ids = {
            row["id"] for row in conn.execute("SELECT id FROM conversations").fetchall()
        }
        desired_ids = {conv.conversation_id for conv in conversations}
        removed = existing_ids - desired_ids
        if removed:
            conn.executemany(
                "DELETE FROM conversations WHERE id = ?", ((conversation_id,) for conversation_id in removed)
            )

        for position, conversation in enumerate(conversations):
            preview = conversation.preview
            conn.execute(
                """
                INSERT INTO conversations (id, position, title, created_at, updated_at, preview)
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
                self._replace_entries(conn, conversation)

    # ------------------------------------------------------------------
    def _replace_entries(
        self, conn: sqlite3.Connection, conversation: ChatConversation
    ) -> None:
        conn.execute(
            "DELETE FROM entries WHERE conversation_id = ?",
            (conversation.conversation_id,),
        )
        for position, entry in enumerate(conversation.entries):
            payload = json.dumps(entry.to_dict(), ensure_ascii=False)
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


__all__ = ["HistoryStore"]
