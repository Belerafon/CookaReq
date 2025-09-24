"""History path helpers for the agent chat panel."""

from __future__ import annotations

from pathlib import Path


def _default_history_path() -> Path:
    """Return default location for persisted chat history."""

    return Path.home() / ".cookareq" / "agent_chats.json"


def _normalize_history_path(path: Path | str) -> Path:
    """Expand user references and coerce *path* into :class:`Path`."""

    return Path(path).expanduser()


def history_path_for_documents(base_directory: Path | str | None) -> Path:
    """Return history file path colocated with a requirements directory."""

    if base_directory is None:
        return _default_history_path()
    base_path = _normalize_history_path(base_directory)
    return base_path / ".cookareq" / "agent_chats.json"


__all__ = ["history_path_for_documents", "_default_history_path", "_normalize_history_path"]
