"""History helpers used by the agent chat panel."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging
from typing import Any

import json

from ...agent.run_contract import (
    AgentRunPayload,
    AgentTimelineEntry,
    LlmStep,
    LlmTrace,
    ToolResultSnapshot,
    build_agent_timeline,
    sort_tool_result_snapshots,
)
from ...agent.timeline_utils import timeline_checksum
from ...util.json import make_json_safe
from ..history_config import HISTORY_JSON_LIMITS
from ...util.strings import coerce_text, describe_unprintable


logger = logging.getLogger(__name__)


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


def _llm_trace_from_preview(
    preview: Sequence[Mapping[str, Any]] | None,
) -> LlmTrace:
    """Build :class:`LlmTrace` from lightweight preview records."""

    steps: list[LlmStep] = []
    if preview:
        for record in preview:
            if not isinstance(record, Mapping):
                continue
            index = record.get("step")
            try:
                step_index = int(index)
            except (TypeError, ValueError):
                continue
            occurred_at = record.get("occurred_at")
            if not isinstance(occurred_at, str) or not occurred_at.strip():
                continue
            request_payload = record.get("request")
            if isinstance(request_payload, Sequence) and not isinstance(
                request_payload, (str, bytes, bytearray)
            ):
                request = [
                    dict(message)
                    for message in request_payload
                    if isinstance(message, Mapping)
                ]
            else:
                request = []
            response_payload = record.get("response")
            response = dict(response_payload) if isinstance(response_payload, Mapping) else {}
            steps.append(
                LlmStep(
                    index=step_index,
                    occurred_at=occurred_at,
                    request=request,
                    response=response,
                )
            )
    return LlmTrace(steps=steps)


def _log_timeline_snapshot(
    timeline: Sequence[AgentTimelineEntry], *, context: str
) -> None:
    if not timeline:
        logger.debug("%s produced an empty agent timeline", context)
        return
    summary = [
        {
            "kind": entry.kind,
            "sequence": entry.sequence,
            "occurred_at": entry.occurred_at,
            "step_index": entry.step_index,
            "call_id": entry.call_id,
            "status": entry.status,
        }
        for entry in timeline
    ]
    logger.debug(
        "%s canonicalised agent timeline (%d events): %s",
        context,
        len(summary),
        summary,
    )


def ensure_canonical_agent_payload(
    payload: AgentRunPayload,
    *,
    tool_snapshots: Sequence[ToolResultSnapshot] | None = None,
    llm_trace_preview: Sequence[Mapping[str, Any]] | None = None,
) -> AgentRunPayload:
    """Attach canonical timeline/tool snapshots before persistence or rendering."""

    if tool_snapshots:
        payload.tool_results = sort_tool_result_snapshots(tool_snapshots)

    if (not payload.llm_trace.steps) and llm_trace_preview:
        payload.llm_trace = _llm_trace_from_preview(llm_trace_preview)

    try:
        payload.timeline = build_agent_timeline(
            payload.events,
            tool_results=payload.tool_results,
            llm_trace=payload.llm_trace,
        )
        payload.timeline_checksum = (
            timeline_checksum(payload.timeline) if payload.timeline else None
        )
    except Exception:
        payload.timeline = []
        payload.timeline_checksum = None
    else:
        if logger.isEnabledFor(logging.DEBUG):
            _log_timeline_snapshot(payload.timeline, context="ensure_canonical_agent_payload")

    return payload


def tool_snapshots_from(value: Any) -> list[ToolResultSnapshot]:
    """Return tool snapshots parsed deterministically from ``value``."""
    if value is None:
        return []
    payload = agent_payload_from_mapping(value) if isinstance(value, Mapping) else None
    if payload is not None:
        return payload.tool_results
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
                fallback = dict(item)
                status_value = fallback.get("status")
                if status_value not in {"pending", "running", "succeeded", "failed"}:
                    agent_status = str(fallback.get("agent_status") or "").lower()
                    match agent_status:
                        case "running":
                            fallback["status"] = "running"
                        case "completed" | "succeeded":
                            fallback["status"] = "succeeded"
                        case "failed":
                            fallback["status"] = "failed"
                fallback.setdefault("tool_name", str(fallback.get("call_id") or "tool"))
                fallback.setdefault("call_id", str(fallback.get("tool_call_id") or ""))
                try:
                    snapshots.append(ToolResultSnapshot.from_dict(fallback))
                except Exception:
                    continue
    if snapshots:
        return sort_tool_result_snapshots(snapshots)
    return snapshots


def tool_messages_from_snapshots(
    snapshots: Sequence[ToolResultSnapshot | Mapping[str, Any]] | None,
) -> tuple[dict[str, Any], ...]:
    """Build transcript-ready tool messages from ``snapshots``.

    The messages mirror what the agent UI displays: a ``tool`` role message per
    call with the serialised snapshot payload as ``content`` and standard
    ``tool_call_id``/``name`` fields so downstream consumers can stitch the
    exchange back into the conversation.
    """

    if not snapshots:
        return ()

    messages: list[dict[str, Any]] = []
    for snapshot in tool_snapshots_from(snapshots):
        payload = snapshot.to_dict()
        identifier = snapshot.call_id
        name = snapshot.tool_name
        content = json.dumps(payload, ensure_ascii=False, default=str)
        message: dict[str, Any] = {"role": "tool", "content": content}
        if identifier:
            message["tool_call_id"] = identifier
        if name:
            message["name"] = name
        messages.append(message)

    return tuple(messages)


def tool_snapshot_dicts(
    snapshots: Sequence[ToolResultSnapshot | Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Serialise ``snapshots`` into dictionaries for persistence.

    Tests stream raw dictionaries into the tool-result handlers, while the
    coordinator delivers :class:`ToolResultSnapshot` instances.  Accept both
    forms so transcript updates do not crash when fed with plain mappings.
    """

    serialised: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if isinstance(snapshot, ToolResultSnapshot):
            serialised.append(snapshot.to_dict())
            continue
        if isinstance(snapshot, Mapping):
            try:
                serialised.append(ToolResultSnapshot.from_dict(snapshot).to_dict())
            except Exception:
                continue
    return serialised


__all__ = [
    "ensure_canonical_agent_payload",
    "agent_payload_from_mapping",
    "history_json_safe",
    "stringify_payload",
    "format_value_snippet",
    "shorten_text",
    "tool_snapshot_dicts",
    "tool_messages_from_snapshots",
    "tool_snapshots_from",
]
