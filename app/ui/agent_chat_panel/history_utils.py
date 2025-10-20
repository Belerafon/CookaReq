"""History helpers used by the agent chat panel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import json

from ...agent.run_contract import AgentRunPayload, ToolResultSnapshot
from ...util.json import make_json_safe


def history_json_safe(value: Any) -> Any:
    """Convert values for history storage using permissive coercions."""
    return make_json_safe(
        value,
        stringify_keys=True,
        sort_sets=False,
        coerce_sequences=True,
        default=str,
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
        return str(payload)


def clone_streamed_tool_results(
    tool_results: Sequence[Mapping[str, Any]] | None,
) -> tuple[dict[str, Any], ...]:
    """Return canonical copies of streamed tool snapshots."""
    if not tool_results:
        return ()
    clones: list[dict[str, Any]] = []
    for payload in tool_results:
        snapshot = _snapshot_from_payload(payload)
        if snapshot is not None:
            clones.append(snapshot.to_dict())
    return tuple(clones)


def looks_like_tool_payload(payload: Mapping[str, Any]) -> bool:
    """Return ``True`` if *payload* resembles a tool snapshot."""
    if not isinstance(payload, Mapping):
        return False
    required_keys = {"call_id", "tool_name", "status"}
    if required_keys.issubset(payload.keys()):
        return True
    try:
        ToolResultSnapshot.from_dict(payload)
    except Exception:
        return False
    return True


def sort_tool_payloads(
    payloads: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return tool payloads sorted by the earliest available timestamp."""
    if not payloads:
        return []
    snapshots: list[dict[str, Any]] = []
    for payload in payloads:
        snapshot = _snapshot_from_payload(payload)
        if snapshot is None:
            continue
        snapshots.append(snapshot.to_dict())

    def timestamp_key(snapshot: dict[str, Any]) -> tuple[str, str]:
        for key in ("started_at", "last_observed_at", "completed_at"):
            value = snapshot.get(key)
            if isinstance(value, str) and value.strip():
                return (value, snapshot.get("call_id", ""))
        return ("", snapshot.get("call_id", ""))

    snapshots.sort(key=timestamp_key)
    return snapshots


def normalise_tool_payloads(tool_results: Any) -> list[dict[str, Any]] | None:
    """Convert *tool_results* to canonical snapshot dictionaries."""
    if tool_results is None:
        return None
    if isinstance(tool_results, Mapping) and "tool_results" in tool_results:
        return normalise_tool_payloads(tool_results.get("tool_results"))
    if isinstance(tool_results, Sequence) and not isinstance(
        tool_results, (str, bytes, bytearray)
    ):
        candidates = tool_results
    else:
        candidates = (tool_results,)
    snapshots: list[dict[str, Any]] = []
    for entry in candidates:
        snapshot = _snapshot_from_payload(entry)
        if snapshot is not None:
            snapshots.append(snapshot.to_dict())
    if not snapshots:
        return None
    return snapshots


def extract_tool_results(raw_result: Any) -> list[dict[str, Any]] | None:
    """Return tool snapshots stored inside *raw_result*."""
    if not isinstance(raw_result, Mapping):
        return None
    return normalise_tool_payloads(raw_result.get("tool_results"))


def update_tool_results(
    raw_result: Any | None, tool_results: Sequence[Any] | None
) -> Any | None:
    """Return ``raw_result`` with deterministic ``tool_results`` section."""
    normalized = normalise_tool_payloads(tool_results)
    if normalized is None:
        if isinstance(raw_result, Mapping) and "tool_results" in raw_result:
            updated = dict(raw_result)
            updated.pop("tool_results", None)
            return updated
        return raw_result
    base = dict(raw_result) if isinstance(raw_result, Mapping) else {}
    base["tool_results"] = normalized
    return base


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
    "clone_streamed_tool_results",
    "looks_like_tool_payload",
    "sort_tool_payloads",
    "normalise_tool_payloads",
    "extract_tool_results",
    "update_tool_results",
    "format_value_snippet",
    "shorten_text",
    "tool_snapshot_dicts",
    "tool_snapshots_from",
]
