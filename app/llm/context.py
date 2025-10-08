"""Helpers for extracting workspace context information for the LLM."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..services.requirements import parse_rid

__all__ = [
    "extract_selected_rids_from_text",
    "extract_selected_rids_from_messages",
]


def extract_selected_rids_from_text(content: str) -> list[str]:
    """Return canonical requirement identifiers from ``content``.

    The agent encodes the currently selected requirements inside the workspace
    context snapshot using a line that starts with ``Selected requirement RIDs:``.
    This helper parses the line, validates every token using
    :func:`parse_rid`, removes duplicates while preserving the original order
    and returns the canonical identifiers. Invalid tokens are ignored so that
    partially malformed selections still yield useful information for the LLM.
    """
    if not isinstance(content, str) or not content:
        return []

    selected: list[str] = []
    seen: set[str] = set()

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("Selected requirement RIDs:"):
            continue
        _, _, remainder = stripped.partition(":")
        values = remainder.strip()
        if not values or values.startswith("("):
            return []
        for token in values.split(","):
            candidate = token.strip()
            if not candidate:
                continue
            try:
                prefix, numeric = parse_rid(candidate)
            except ValueError:
                continue
            rid = f"{prefix}{numeric}"
            if rid in seen:
                continue
            seen.add(rid)
            selected.append(rid)
        break

    return selected


def extract_selected_rids_from_messages(
    messages: Sequence[Mapping[str, Any]] | None,
) -> list[str]:
    """Scan *messages* and return selected RIDs referenced in system snapshots."""
    if not messages:
        return []

    aggregated: list[str] = []
    seen: set[str] = set()
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        if message.get("role") != "system":
            continue
        content = message.get("content")
        if not isinstance(content, str):
            continue
        rids = extract_selected_rids_from_text(content)
        if not rids:
            continue
        for rid in rids:
            if rid in seen:
                continue
            aggregated.append(rid)
            seen.add(rid)
    return aggregated
