"""Utilities for deriving MCP filesystem locations."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DocumentsRootDescription:
    """Metadata about the resolved documentation directory."""

    status: Literal["disabled", "missing_base", "invalid", "resolved"]
    input_path: str = ""
    resolved: Path | None = None
    is_relative: bool = False


def normalize_documents_path(value: str | Path | None) -> str:
    """Return ``value`` as a trimmed string suitable for persistence."""

    if value is None:
        return ""
    if isinstance(value, Path):
        text = str(value)
    else:
        text = str(value)
    return text.strip()


def describe_documents_root(
    base_path: str | Path | None,
    documents_path: str | Path | None,
) -> DocumentsRootDescription:
    """Return a structured description of the documentation directory."""

    text = normalize_documents_path(documents_path)
    if not text:
        return DocumentsRootDescription(status="disabled")
    try:
        candidate = Path(text).expanduser()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Invalid documents path %s: %s", documents_path, exc)
        return DocumentsRootDescription(status="invalid", input_path=text)
    if candidate.is_absolute():
        return DocumentsRootDescription(
            status="resolved",
            input_path=text,
            resolved=candidate,
            is_relative=False,
        )
    if base_path in (None, ""):
        return DocumentsRootDescription(
            status="missing_base",
            input_path=text,
            is_relative=True,
        )
    try:
        base = Path(base_path).expanduser()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Invalid requirements base %s: %s", base_path, exc)
        return DocumentsRootDescription(
            status="invalid", input_path=text, is_relative=True
        )
    resolved = (base / candidate).resolve(strict=False)
    return DocumentsRootDescription(
        status="resolved",
        input_path=text,
        resolved=resolved,
        is_relative=True,
    )


def resolve_documents_root(
    base_path: str | Path | None,
    documents_path: str | Path | None,
) -> Path | None:
    """Resolve the documentation directory combining base and document paths."""

    description = describe_documents_root(base_path, documents_path)
    if description.status != "resolved":
        return None
    return description.resolved


__all__ = [
    "DocumentsRootDescription",
    "describe_documents_root",
    "normalize_documents_path",
    "resolve_documents_root",
]
