"""History helpers used by the agent chat panel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import json

from ...agent.run_contract import AgentRunPayload, ToolResultSnapshot
from ...util.json import make_json_safe
from ..history_config import HISTORY_JSON_LIMITS
from ...util.strings import coerce_text, describe_unprintable


def history_json_safe(value: Any) -> Any:
    """Convert values for history storage using permissive coercions."""
    return make_json_safe(
        value,
        stringify_keys=True,
        sort_sets=False,
        coerce_sequences=True,
        default=str,
        limits=HISTORY_JSON_LIMITS,
    )


def stringify_payload(payload: Any) -> str:
    """Return textual representation suitable for transcript storage."""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        text = coerce_text(
            payload,
            allow_empty=True,
            fallback_factory=lambda value: describe_unprintable(
                value, prefix="unserialisable payload"
            ),
        )
        return text or ""


def format_value_snippet(value: Any) -> str:
    """Produce a human-friendly snippet for diagnostic payloads."""
    from .tool_summaries import format_value_snippet as _format_value_snippet

    return _format_value_snippet(value)


def shorten_text(text: str, *, limit: int = 120) -> str:
    """Truncate ``text`` to ``limit`` characters preserving ellipsis."""
    from .tool_summaries import shorten_text as _shorten_text

    return _shorten_text(text, limit=limit)


def _snapshot_from_payload(payload: Any) -> ToolResultSnapshot | None:
    if isinstance(payload, ToolResultSnapshot):
        return payload
    if isinstance(payload, Mapping):
        try:
            return ToolResultSnapshot.from_dict(payload)
        except Exception:
            return None
    return None


def agent_payload_from_mapping(payload: Mapping[str, Any] | None) -> AgentRunPayload | None:
    """Parse ``payload`` as :class:`AgentRunPayload` when possible."""
    if not isinstance(payload, Mapping):
        return None
    try:
        return AgentRunPayload.from_dict(payload)
    except Exception:
        return None


def tool_snapshots_from(value: Any) -> list[ToolResultSnapshot]:
    """Return tool snapshots parsed deterministically from ``value``."""
    if value is None:
        return []
    if isinstance(value, Mapping) and "tool_results" in value:
        return tool_snapshots_from(value.get("tool_results"))
    if isinstance(value, ToolResultSnapshot):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        candidates = value
    else:
        candidates = (value,)
    snapshots: list[ToolResultSnapshot] = []
    for item in candidates:
        if isinstance(item, ToolResultSnapshot):
            snapshots.append(item)
            continue
        if isinstance(item, Mapping):
            try:
                snapshots.append(ToolResultSnapshot.from_dict(item))
            except Exception:
                continue
    return snapshots


def tool_snapshot_dicts(snapshots: Sequence[ToolResultSnapshot]) -> list[dict[str, Any]]:
    """Serialise ``snapshots`` into dictionaries for persistence."""
    return [snapshot.to_dict() for snapshot in snapshots]


__all__ = [
    "agent_payload_from_mapping",
    "history_json_safe",
    "stringify_payload",
    "format_value_snippet",
    "shorten_text",
    "tool_snapshot_dicts",
    "tool_snapshots_from",
]
