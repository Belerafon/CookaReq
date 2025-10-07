"""History helpers used by the agent chat panel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import json

from ...util.json import make_json_safe
from ..text import normalize_for_display
from .time_formatting import parse_iso_timestamp


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


def looks_like_tool_payload(payload: Mapping[str, Any]) -> bool:
    """Heuristically determine whether *payload* originates from an MCP tool."""

    def _has_text(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    def _has_meaningful(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, Mapping):
            return any(_has_meaningful(item) for item in value.values())
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return any(_has_meaningful(item) for item in value)
        return True

    identifier_keys = ("tool_call_id", "call_id", "call_identifier", "id")
    argument_keys = ("tool_arguments", "arguments", "args")

    if _has_text(payload.get("tool_name")) or _has_text(payload.get("tool")):
        return True

    for key in identifier_keys:
        if _has_text(payload.get(key)):
            return True

    for key in argument_keys:
        if _has_meaningful(payload.get(key)):
            return True

    tool_section = payload.get("tool")
    if isinstance(tool_section, Mapping):
        if _has_text(tool_section.get("name")):
            return True
        for key in identifier_keys:
            if _has_text(tool_section.get(key)):
                return True
        for key in argument_keys:
            if _has_meaningful(tool_section.get(key)):
                return True

    if _has_text(payload.get("name")):
        for key in argument_keys:
            if _has_meaningful(payload.get(key)):
                return True

    return False


def clone_streamed_tool_results(
    tool_results: Sequence[Mapping[str, Any]] | None,
) -> tuple[dict[str, Any], ...]:
    """Return a defensive copy of streamed tool payloads."""

    if not tool_results:
        return ()
    clones: list[dict[str, Any]] = []
    for payload in tool_results:
        if isinstance(payload, Mapping):
            clones.append(dict(payload))
    return tuple(clones)


def sort_tool_payloads(
    payloads: Sequence[Any] | None,
) -> list[Any]:
    """Return payloads ordered by their earliest recorded timestamp."""

    if not payloads:
        return []

    ranked: list[tuple[tuple[Any, ...], Any]] = []
    for index, payload in enumerate(payloads):
        if isinstance(payload, Mapping):
            timestamps = (
                payload.get("first_observed_at"),
                payload.get("started_at"),
                payload.get("observed_at"),
                payload.get("last_observed_at"),
                payload.get("completed_at"),
            )
            moment = None
            for candidate in timestamps:
                moment = parse_iso_timestamp(candidate)
                if moment is not None:
                    break
            if moment is not None:
                ranked.append(((0, moment, index), payload))
                continue
        ranked.append(((1, index), payload))

    ranked.sort(key=lambda item: item[0])
    return [payload for _, payload in ranked]


def normalise_tool_payloads(tool_results: Any) -> list[Any] | None:
    """Return sorted tool payloads from *tool_results* or ``None``."""

    if not tool_results:
        return None

    if isinstance(tool_results, Mapping) and "tool_results" in tool_results:
        nested = tool_results.get("tool_results")
        return normalise_tool_payloads(nested)

    if isinstance(tool_results, Sequence) and not isinstance(
        tool_results, (str, bytes, bytearray)
    ):
        candidates = list(tool_results)
    else:
        candidates = [tool_results]

    serialised: list[Any] = []
    for payload in candidates:
        if payload is None:
            continue
        serialised.append(history_json_safe(payload))

    if not serialised:
        return None

    return sort_tool_payloads(serialised)


def extract_tool_results(raw_result: Any) -> list[Any] | None:
    """Pull tool payloads from *raw_result* if present."""

    if not isinstance(raw_result, Mapping):
        return None
    return normalise_tool_payloads(raw_result.get("tool_results"))


def update_tool_results(
    raw_result: Any | None, tool_results: Sequence[Any] | None
) -> Any | None:
    """Return ``raw_result`` with the provided ``tool_results`` merged in."""

    normalised = normalise_tool_payloads(tool_results)

    if normalised is None:
        if isinstance(raw_result, Mapping) and "tool_results" in raw_result:
            updated = dict(raw_result)
            updated.pop("tool_results", None)
            return updated
        return raw_result

    if isinstance(raw_result, Mapping):
        updated = dict(raw_result)
    else:
        updated = {}

    updated["tool_results"] = normalised
    return updated


def format_value_snippet(value: Any) -> str:
    """Produce a human-friendly snippet for diagnostic payloads."""

    from .tool_summaries import format_value_snippet as _format_value_snippet

    return _format_value_snippet(value)


def shorten_text(text: str, *, limit: int = 120) -> str:
    """Truncate ``text`` to ``limit`` characters preserving ellipsis."""

    from .tool_summaries import shorten_text as _shorten_text

    return _shorten_text(text, limit=limit)


__all__ = [
    "history_json_safe",
    "stringify_payload",
    "looks_like_tool_payload",
    "clone_streamed_tool_results",
    "sort_tool_payloads",
    "normalise_tool_payloads",
    "extract_tool_results",
    "update_tool_results",
    "format_value_snippet",
    "shorten_text",
]
