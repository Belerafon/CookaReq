"""Utilities for deriving MCP filesystem locations."""

from __future__ import annotations

import logging
from pathlib import Path
logger = logging.getLogger(__name__)


def normalize_documents_path(value: str | Path | None) -> str:
    """Return ``value`` as a trimmed string suitable for persistence."""

    if value is None:
        return ""
    if isinstance(value, Path):
        text = str(value)
    else:
        text = str(value)
    return text.strip()


def resolve_documents_root(
    base_path: str | Path | None,
    documents_path: str | Path | None,
) -> Path | None:
    """Resolve the documentation directory combining base and document paths."""

    text = normalize_documents_path(documents_path)
    if not text:
        return None
    try:
        candidate = Path(text).expanduser()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Invalid documents path %s: %s", documents_path, exc)
        return None
    if candidate.is_absolute():
        return candidate
    if base_path in (None, ""):
        return None
    try:
        base = Path(base_path).expanduser()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Invalid requirements base %s: %s", base_path, exc)
        return None
    return (base / candidate).resolve(strict=False)


__all__ = [
    "normalize_documents_path",
    "resolve_documents_root",
]
