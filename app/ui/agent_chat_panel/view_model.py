"""Turn-oriented view model for the agent chat transcript."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from collections.abc import Iterable, Mapping, Sequence
import re
from typing import Any, Literal, TYPE_CHECKING

from ...agent.run_contract import (
    AgentEvent,
    AgentEventLog,
    AgentRunPayload,
    AgentTimelineEntry,
    LlmTrace,
    LlmStep,
    ToolResultSnapshot,
)
from ...agent.timeline_utils import (
    TimelineIntegrity,
    assess_timeline_integrity,
    timeline_checksum,
)
from ...agent.run_contract import build_agent_timeline
from ..text import normalize_for_display
from ...util.time import utc_now_iso
from .history_utils import (
    agent_payload_from_mapping,
    history_json_safe,
    tool_snapshots_from,
)
from .time_formatting import format_entry_timestamp, parse_iso_timestamp
from .tool_summaries import ToolCallSummary, summarize_tool_results

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from ..chat_entry import ChatConversation, ChatEntry
else:  # pragma: no cover - runtime avoids circular import
    ChatConversation = Any  # type: ignore[assignment]
    ChatEntry = Any  # type: ignore[assignment]


_UTC_MIN = _dt.datetime.min.replace(tzinfo=_dt.timezone.utc)

_BR_TAG_PATTERN = re.compile(r"[ \t\f\v]*<br\s*/?>[ \t\f\v]*", flags=re.IGNORECASE)
_SPACE_RUN_PATTERN = re.compile(r"[ \t\f\v]{2,}(?!\n)")


@dataclass(slots=True)
class TimestampInfo:
    """A timestamp extracted from chat data."""

    raw: str | None
    occurred_at: _dt.datetime | None
    formatted: str
    missing: bool
    source: str | None = None


@dataclass(slots=True)
class PromptMessage:
    """User message directed at the agent."""

    text: str
    timestamp: TimestampInfo


@dataclass(slots=True)
class AgentResponse:
    """Single textual response emitted by the agent."""

    text: str
    display_text: str
    timestamp: TimestampInfo
    step_index: int | None
    is_final: bool
    regenerated: bool = False


@dataclass(slots=True)
class AgentTimelineEvent:
    """An item in the agent turn timeline."""

    kind: Literal["response", "tool"]
    timestamp: TimestampInfo
    order_index: int
    sequence: int | None = None
    response: AgentResponse | None = None
    tool_call: "ToolCallDetails" | None = None


@dataclass(slots=True)
class LlmRequestSnapshot:
    """Recorded messages that were sent to the language model."""

    messages: tuple[dict[str, Any], ...]
    sequence: tuple[dict[str, Any], ...] | None


@dataclass(slots=True)
class ToolCallDetails:
    """Diagnostic information about an MCP tool invocation."""

    summary: ToolCallSummary
    call_identifier: str | None
    raw_data: Any | None
    timestamp: TimestampInfo
    step_index: int | None = None
    llm_request: dict[str, Any] | None = None


@dataclass(slots=True)
class AgentTurn:
    """Aggregated information about a single agent turn."""

    entry_id: str
    entry_index: int
    occurred_at: _dt.datetime | None
    timestamp: TimestampInfo
    streamed_responses: tuple[AgentResponse, ...]
    final_response: AgentResponse | None
    reasoning: tuple[dict[str, Any], ...]
    reasoning_by_step: dict[int, tuple[dict[str, Any], ...]]
    llm_request: LlmRequestSnapshot | None
    tool_calls: tuple[ToolCallDetails, ...]
    raw_payload: Any | None
    events: tuple[AgentTimelineEvent, ...]
    event_signature: tuple[tuple[Any, ...], ...] = ()
    timeline_is_authoritative: bool = False
    timeline_source: Literal["payload", "event_log", "missing"] = "missing"
    timeline_fingerprint: tuple[Any, ...] | None = None


@dataclass(slots=True)
class SystemMessage:
    """System-level diagnostic entry attached to the transcript."""

    message: str
    details: Any | None = None


@dataclass(slots=True)
class TranscriptEntry:
    """Combined representation of a prompt and the corresponding agent turn."""

    entry_id: str
    entry_index: int
    entry: ChatEntry
    prompt: PromptMessage | None
    context_messages: tuple[dict[str, Any], ...]
    agent_turn: AgentTurn | None
    system_messages: tuple[SystemMessage, ...]
    layout_hints: dict[str, int]
    can_regenerate: bool


@dataclass(slots=True)
class ConversationTimeline:
    """Timeline representation of a conversation ready for rendering."""

    conversation_id: str
    entries: tuple[TranscriptEntry, ...]


@dataclass(slots=True)
class PromptSegment:
    """Prompt-related payload rendered as a message segment."""

    prompt: PromptMessage | None
    context_messages: tuple[dict[str, Any], ...]
    layout_hints: dict[str, int]


@dataclass(slots=True)
class AgentSegment:
    """Agent turn payload rendered as a message segment."""

    turn: AgentTurn | None
    layout_hints: dict[str, int]
    can_regenerate: bool


@dataclass(slots=True)
class TranscriptSegment:
    """Flattened representation of transcript data."""

    segment_id: str
    entry_id: str
    entry_index: int
    kind: Literal["user", "agent", "system"]
    payload: PromptSegment | AgentSegment | SystemMessage


@dataclass(slots=True)
class TranscriptSegments:
    """Ordered segment list for a conversation."""

    conversation_id: str
    entry_order: tuple[str, ...]
    segments: tuple[TranscriptSegment, ...]


@dataclass(slots=True)
class _CachedTimeline:
    timeline: ConversationTimeline
    entry_map: dict[str, TranscriptEntry]
    entry_fingerprints: dict[str, tuple[Any, ...] | None]


# ---------------------------------------------------------------------------
def _build_timestamp(value: str | None, *, source: str | None) -> TimestampInfo:
    if isinstance(value, str):
        text = value.strip()
        if text:
            occurred_at = parse_iso_timestamp(text)
            formatted = format_entry_timestamp(text)
            return TimestampInfo(
                raw=text,
                occurred_at=occurred_at,
                formatted=formatted,
                missing=False,
                source=source,
            )
    return TimestampInfo(
        raw=None,
        occurred_at=None,
        formatted="",
        missing=True,
        source=source,
    )


def _sanitize_mapping_sequence(
    sequence: Sequence[Mapping[str, Any]] | None,
) -> tuple[dict[str, Any], ...]:
    if not sequence:
        return ()
    sanitized: list[dict[str, Any]] = []
    for item in sequence:
        safe_item = history_json_safe(item)
        if isinstance(safe_item, Mapping):
            sanitized.append(dict(safe_item))
    return tuple(sanitized)


def _render_reasoning_fallback(
    segments: Sequence[Mapping[str, Any]] | None,
) -> str:
    if not segments:
        return ""
    parts: list[str] = []
    for segment in segments:
        if not isinstance(segment, Mapping):
            continue
        text = str(segment.get("text") or "")
        leading = str(segment.get("leading_whitespace") or "")
        trailing = str(segment.get("trailing_whitespace") or "")
        combined = f"{leading}{text}{trailing}"
        if combined.strip():
            parts.append(combined)
    if not parts:
        return ""
    return "".join(parts).strip()


def _build_prompt(entry: ChatEntry) -> PromptMessage | None:
    text = entry.prompt or ""
    timestamp = _build_timestamp(entry.prompt_at, source="prompt_at")
    if not text and not timestamp.raw:
        return None
    return PromptMessage(text=text, timestamp=timestamp)


def _build_context_messages(entry: ChatEntry) -> tuple[dict[str, Any], ...]:
    return entry.sanitized_context_messages()


def _build_llm_trace_from_diagnostic(
    diagnostic: Mapping[str, Any] | None,
    *,
    prompt_timestamp: TimestampInfo,
    response_timestamp: TimestampInfo,
) -> LlmTrace | None:
    if not isinstance(diagnostic, Mapping):
        return None
    steps_payload = diagnostic.get("llm_steps")
    if not isinstance(steps_payload, Sequence) or isinstance(
        steps_payload, (str, bytes, bytearray)
    ):
        return None

    fallback_timestamp = (
        prompt_timestamp.occurred_at
        or response_timestamp.occurred_at
        or prompt_timestamp.raw
        or response_timestamp.raw
        or utc_now_iso()
    )
    if isinstance(fallback_timestamp, _dt.datetime):
        fallback_timestamp = fallback_timestamp.isoformat()
    elif not isinstance(fallback_timestamp, str):
        fallback_timestamp = utc_now_iso()

    steps: list[LlmStep] = []
    for index, payload in enumerate(steps_payload, start=1):
        if not isinstance(payload, Mapping):
            continue
        occurred_at = payload.get("occurred_at") or payload.get("timestamp")
        if not occurred_at:
            response_payload = payload.get("response")
            if isinstance(response_payload, Mapping):
                occurred_at = response_payload.get("timestamp")
        occurred_text = (
            occurred_at
            if isinstance(occurred_at, str) and occurred_at.strip()
            else fallback_timestamp
        )
        step_index_value = payload.get("step") or payload.get("index") or index
        try:
            step_index = int(step_index_value)
        except Exception:
            step_index = index
        request_payload = payload.get("request")
        request: list[dict[str, Any]]
        if isinstance(request_payload, Sequence) and not isinstance(
            request_payload, (str, bytes, bytearray)
        ):
            request = [dict(message) for message in request_payload if isinstance(message, Mapping)]
        else:
            request = []
        response_payload = payload.get("response")
        response: dict[str, Any] = (
            dict(response_payload) if isinstance(response_payload, Mapping) else {}
        )
        try:
            steps.append(
                LlmStep(
                    index=step_index,
                    occurred_at=occurred_text,
                    request=tuple(request),
                    response=response,
                )
            )
        except Exception:
            continue

    if not steps:
        return None
    return LlmTrace(steps=steps)


def _timeline_integrity(
    entry: ChatEntry, payload: AgentRunPayload | None
) -> TimelineIntegrity:
    declared_checksum: str | None = None
    if payload is not None:
        declared_checksum = payload.timeline_checksum or entry.timeline_checksum
        integrity = assess_timeline_integrity(
            payload.timeline, declared_checksum=declared_checksum
        )
    else:
        integrity = assess_timeline_integrity((), declared_checksum=entry.timeline_checksum)

    if entry.timeline_status == "damaged" and integrity.status == "valid":
        integrity = TimelineIntegrity(
            status="damaged",
            checksum=integrity.checksum,
            issues=integrity.issues + ("history_marked_damaged",),
        )
    if entry.timeline_status == "missing" and integrity.status != "missing":
        integrity = TimelineIntegrity(
            status="missing",
            checksum=integrity.checksum,
            issues=integrity.issues + ("history_marked_missing",),
        )
    return integrity


def _agent_timeline_fingerprint(
    payload: AgentRunPayload | None,
    tool_snapshots: Sequence[ToolResultSnapshot],
    llm_trace: LlmTrace,
    integrity: TimelineIntegrity,
) -> tuple[Any, ...]:
    if payload is not None and payload.timeline and integrity.status == "valid":
        checksum = (
            integrity.checksum
            or payload.timeline_checksum
            or timeline_checksum(payload.timeline)
        )
        return ("timeline", len(payload.timeline), checksum)

    return (
        "fallback",
        integrity.status,
        integrity.checksum or payload.timeline_checksum if payload is not None else None,
        len(tool_snapshots),
        len(llm_trace.steps),
    )


def _collect_agent_sources(
    entry: ChatEntry,
) -> tuple[
    AgentRunPayload | None,
    AgentEventLog,
    tuple[ToolResultSnapshot, ...],
    LlmTrace,
    Any,
    TimestampInfo,
    TimestampInfo,
    Mapping[str, Any] | None,
    str,
]:
    response_timestamp = _build_timestamp(entry.response_at, source="response_at")
    prompt_timestamp = _build_timestamp(entry.prompt_at, source="prompt_at")

    raw_result = entry.raw_result if isinstance(entry.raw_result, Mapping) else None
    diagnostic_payload = entry.diagnostic if isinstance(entry.diagnostic, Mapping) else None
    if diagnostic_payload is None and isinstance(raw_result, Mapping):
        candidate = raw_result.get("diagnostic")
        if isinstance(candidate, Mapping):
            diagnostic_payload = candidate

    payload = agent_payload_from_mapping(raw_result)
    event_log = AgentEventLog()
    tool_snapshots: tuple[ToolResultSnapshot, ...]
    reasoning_source: Any

    if payload is None:
        tool_snapshots = tool_snapshots_from(entry.tool_results or raw_result)
        reasoning_source = entry.reasoning or (
            diagnostic_payload.get("reasoning") if diagnostic_payload else None
        )
        if diagnostic_payload and isinstance(diagnostic_payload, Mapping):
            diagnostic_event_log = diagnostic_payload.get("event_log")
            if isinstance(diagnostic_event_log, Sequence):
                try:
                    event_log = AgentEventLog.from_dict({"events": diagnostic_event_log})
                except Exception:
                    event_log = AgentEventLog()
        llm_trace = _build_llm_trace_from_diagnostic(
            diagnostic_payload,
            prompt_timestamp=prompt_timestamp,
            response_timestamp=response_timestamp,
        )
        if llm_trace is None:
            llm_trace = LlmTrace()
        final_text = entry.display_response or entry.response or ""
    else:
        event_log = payload.events
        if not event_log.events and diagnostic_payload:
            diagnostic_event_log = diagnostic_payload.get("event_log")
            if isinstance(diagnostic_event_log, Sequence):
                try:
                    event_log = AgentEventLog.from_dict({"events": diagnostic_event_log})
                except Exception:
                    event_log = payload.events
        tool_snapshots = payload.tool_results
        reasoning_source = payload.reasoning or (
            diagnostic_payload.get("reasoning") if diagnostic_payload else None
        )
        llm_trace = payload.llm_trace
        if not llm_trace.steps:
            fallback_trace = _build_llm_trace_from_diagnostic(
                diagnostic_payload,
                prompt_timestamp=prompt_timestamp,
                response_timestamp=response_timestamp,
            )
            if fallback_trace is not None:
                llm_trace = fallback_trace
        final_text = (
            entry.display_response
            or payload.result_text
            or entry.response
            or getattr(payload, "message_preview", "")
            or ""
        )

    return (
        payload,
        event_log,
        tool_snapshots,
        llm_trace,
        reasoning_source,
        prompt_timestamp,
        response_timestamp,
        diagnostic_payload,
        final_text,
    )


def _resolve_agent_timeline(
    entry: ChatEntry,
    payload: AgentRunPayload | None,
    event_log: AgentEventLog,
    tool_snapshots: Sequence[ToolResultSnapshot],
    llm_trace: LlmTrace,
    *,
    integrity: TimelineIntegrity | None = None,
) -> tuple[tuple[AgentTimelineEntry, ...], Literal["payload", "missing"], str]:
    cache = entry._ensure_view_cache()
    integrity = integrity or _timeline_integrity(entry, payload)
    fingerprint = _agent_timeline_fingerprint(
        payload, tool_snapshots, llm_trace, integrity
    )

    cached_entries = cache.get("agent_timeline_entries")
    cached_fingerprint = cache.get("agent_timeline_entries_fingerprint")
    if cached_entries is not None and cached_fingerprint == fingerprint:
        return cached_entries

    source: Literal["payload", "missing"] = "missing"
    timeline_entries: tuple[AgentTimelineEntry, ...] = ()
    timeline_status = integrity.status

    if payload is not None and payload.timeline and integrity.status == "valid":
        timeline_entries = tuple(payload.timeline)
        source = "payload"
    elif payload is not None and payload.timeline:
        source = "payload"

    if not timeline_entries:
        reconstructed = build_agent_timeline(
            event_log,
            tool_results=tool_snapshots,
            llm_trace=llm_trace,
        )
        if reconstructed:
            timeline_entries = tuple(reconstructed)
            timeline_integrity = assess_timeline_integrity(
                timeline_entries,
                declared_checksum=payload.timeline_checksum
                if payload is not None
                else entry.timeline_checksum,
            )
            timeline_status = timeline_integrity.status
            source = "payload"

    cache["agent_timeline_entries_fingerprint"] = fingerprint
    cache["agent_timeline_entries"] = (timeline_entries, source, timeline_status)
    return timeline_entries, source, timeline_status


def _agent_timeline_fingerprint_for_entry(entry: ChatEntry) -> tuple[Any, ...]:
    cache = entry._ensure_view_cache()
    cached = cache.get("agent_timeline_fingerprint")
    if cached is not None:
        return cached

    (
        payload,
        event_log,
        tool_snapshots,
        llm_trace,
        _reasoning_source,
        _prompt_timestamp,
        _response_timestamp,
        _diagnostic_payload,
        _final_text,
    ) = _collect_agent_sources(entry)

    integrity = _timeline_integrity(entry, payload)
    fingerprint = _agent_timeline_fingerprint(
        payload, tool_snapshots, llm_trace, integrity
    )
    cache["agent_timeline_fingerprint"] = fingerprint
    return fingerprint


def _build_agent_turn(
    entry_id: str,
    entry_index: int,
    entry: ChatEntry,
) -> AgentTurn | None:
    (
        payload,
        event_log,
        tool_snapshots,
        llm_trace,
        reasoning_source,
        prompt_timestamp,
        response_timestamp,
        diagnostic_payload,
        final_text,
    ) = _collect_agent_sources(entry)

    integrity = _timeline_integrity(entry, payload)
    timeline_entries, timeline_source, timeline_status = _resolve_agent_timeline(
        entry,
        payload,
        event_log,
        tool_snapshots,
        llm_trace,
        integrity=integrity,
    )

    for event in event_log.events:
        if event.kind == "agent_finished":
            finished_timestamp = _build_timestamp(
                event.occurred_at, source="agent_finished"
            )
            if not finished_timestamp.missing:
                response_timestamp = finished_timestamp

    for timeline_entry in timeline_entries:
        if timeline_entry.kind == "agent_finished" and timeline_entry.occurred_at:
            finished_timestamp = _build_timestamp(
                timeline_entry.occurred_at, source="timeline"
            )
            if not finished_timestamp.missing:
                response_timestamp = finished_timestamp

    raw_payload = entry.history_safe_raw_result()
    reasoning_segments: list[dict[str, Any]] = list(
        entry.cache_view_value(
            "reasoning_segments",
            lambda: _sanitize_mapping_sequence(reasoning_source),
        )
    )

    reasoning_by_step: dict[int, tuple[dict[str, Any], ...]] = {}

    def _reasoning_key(segment: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            segment.get("type"),
            segment.get("text"),
            segment.get("leading_whitespace"),
            segment.get("trailing_whitespace"),
        )

    seen_keys = {_reasoning_key(segment) for segment in reasoning_segments}

    if llm_trace.steps:
        for position, step in enumerate(llm_trace.steps, start=1):
            step_index = step.index if step.index is not None else position
            step_reasoning = _sanitize_mapping_sequence(step.response.get("reasoning"))
            collected_for_step: list[dict[str, Any]] = []
            for segment in step_reasoning:
                key = _reasoning_key(segment)
                if key not in seen_keys:
                    reasoning_segments.append(segment)
                    seen_keys.add(key)
                collected_for_step.append(segment)
            if collected_for_step:
                reasoning_by_step[step_index] = tuple(collected_for_step)

    reasoning_segments = tuple(reasoning_segments)
    entry._ensure_view_cache()["reasoning_segments"] = reasoning_segments

    reasoning_fallback = _render_reasoning_fallback(reasoning_segments)
    reasoning_display = entry.cache_view_value(
        "reasoning_display",
        lambda: normalize_for_display(reasoning_fallback),
    )

    final_response = _build_final_response(
        final_text,
        response_timestamp,
        regenerated=bool(getattr(entry, "regenerated", False)),
    )

    if final_response is not None and final_response.step_index is None:
        if llm_trace.steps:
            last_index = llm_trace.steps[-1].index
            if last_index is None:
                last_index = len(llm_trace.steps)
            final_response.step_index = last_index

    excluded_displays: set[str] = set()
    if reasoning_display:
        excluded_displays.add(reasoning_display)
    if final_response is not None:
        final_display = final_response.display_text or ""
        if final_display:
            excluded_displays.add(final_display)

    if llm_trace.steps:
        fallback_timestamp = prompt_timestamp.occurred_at or response_timestamp.occurred_at
        for step in llm_trace.steps:
            if not step.occurred_at:
                if fallback_timestamp is not None:
                    step.occurred_at = fallback_timestamp.isoformat()
                elif prompt_timestamp.raw:
                    step.occurred_at = prompt_timestamp.raw
            if not step.request:
                step.request = ({"role": "user", "content": entry.prompt},)
    streamed_responses, latest_stream_timestamp = _build_streamed_responses(
        llm_trace,
        final_response,
        excluded_displays,
    )
    tool_calls, latest_tool_timestamp = _build_tool_calls(
        entry_id, tool_snapshots, llm_trace
    )
    events = _build_agent_events(
        streamed_responses,
        final_response,
        tool_calls,
        timeline=timeline_entries,
        timeline_status=timeline_status,
    )

    timeline_fingerprint = _agent_timeline_fingerprint(
        payload, tool_snapshots, llm_trace, integrity
    )
    entry._ensure_view_cache()["agent_timeline_fingerprint"] = timeline_fingerprint

    resolved_timestamp = _resolve_turn_timestamp(
        response_timestamp,
        prompt_timestamp,
        timeline_timestamp=_timeline_timestamp(timeline_entries),
        event_log_timestamp=_event_log_timestamp(event_log),
        llm_trace_timestamp=_llm_trace_timestamp(llm_trace),
    )

    updated_events = False
    if final_response is not None:
        should_update_final_timestamp = (
            final_response.timestamp.missing
            or (
                resolved_timestamp.occurred_at is not None
                and (
                    final_response.timestamp.occurred_at is None
                    or final_response.timestamp.occurred_at
                    < resolved_timestamp.occurred_at
                )
            )
        )
        if should_update_final_timestamp:
            final_response.timestamp = resolved_timestamp
            updated_events = True

    if updated_events:
        events = _build_agent_events(
            streamed_responses,
            final_response,
            tool_calls,
            timeline=timeline_entries,
            timeline_status=timeline_status,
        )
        resolved_timestamp = _resolve_turn_timestamp(
            final_response.timestamp,
            prompt_timestamp,
            timeline_timestamp=_timeline_timestamp(timeline_entries),
            event_log_timestamp=_event_log_timestamp(event_log),
            llm_trace_timestamp=_llm_trace_timestamp(llm_trace),
        )

    occurred_at = resolved_timestamp.occurred_at
    llm_request = _build_llm_request_snapshot(llm_trace)
    if llm_request is None:
        default_messages: list[dict[str, Any]] = []
        if entry.context_messages:
            default_messages.extend(dict(message) for message in entry.context_messages)
        default_messages.append({"role": "user", "content": entry.prompt})
        llm_request = LlmRequestSnapshot(messages=tuple(default_messages), sequence=None)

    ordered_events: list[AgentTimelineEvent] = []
    preserve_timeline_order = bool(timeline_entries)

    def _event_sort_key(ev: AgentTimelineEvent) -> tuple[Any, ...]:
        if preserve_timeline_order and ev.sequence is not None:
            return (0, ev.sequence)
        timestamp = ev.timestamp
        if timestamp.occurred_at is not None:
            ts_key = (False, timestamp.occurred_at.isoformat(), timestamp.raw or "")
        elif timestamp.raw:
            ts_key = (False, "", timestamp.raw)
        else:
            ts_key = (True, "", "")
        return (
            1,
            ts_key[0],
            ts_key[1],
            ts_key[2],
            0 if ev.kind == "response" else 1,
            ev.sequence,
        )

    for index, event in enumerate(sorted(events, key=_event_sort_key)):
        event.order_index = index
        if not preserve_timeline_order or event.sequence is None:
            event.sequence = index
        ordered_events.append(event)

    events = tuple(ordered_events)

    has_content = bool(
        final_response
        or streamed_responses
        or reasoning_segments
        or tool_calls
        or (raw_payload is not None)
    )

    if not has_content and not resolved_timestamp.raw:
        return None

    return AgentTurn(
        entry_id=entry_id,
        entry_index=entry_index,
        occurred_at=occurred_at,
        timestamp=resolved_timestamp,
        streamed_responses=streamed_responses,
        final_response=final_response,
        reasoning=reasoning_segments,
        reasoning_by_step=reasoning_by_step,
        llm_request=llm_request,
        tool_calls=tool_calls,
        raw_payload=raw_payload,
        events=events,
        event_signature=agent_turn_event_signature(events),
        timeline_is_authoritative=bool(timeline_entries),
        timeline_source=timeline_source,
        timeline_fingerprint=timeline_fingerprint,
    )


def _prepare_agent_display_text(value: str | None) -> str:
    if not value:
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = _BR_TAG_PATTERN.sub("  \n", text)
    text = _SPACE_RUN_PATTERN.sub(" ", text)
    return text.strip(" \t\f\v")


def _normalize_agent_display_text(value: str | None) -> str:
    """Normalize agent text to a comparable display form."""

    return normalize_for_display(_prepare_agent_display_text(value))


def _persist_canonical_timeline(
    entry: ChatEntry,
    payload: AgentRunPayload | None,
    timeline_entries: Sequence[AgentTimelineEntry],
) -> None:
    if not timeline_entries:
        return

    if payload is not None:
        payload.timeline = list(timeline_entries)

    raw_result = getattr(entry, "raw_result", None)
    updated_raw: dict[str, Any]
    if isinstance(raw_result, Mapping):
        updated_raw = dict(raw_result)
    else:
        updated_raw = {}

    updated_raw["timeline"] = [
        timeline_entry.to_dict() for timeline_entry in timeline_entries
    ]

    if payload is not None and "events" not in updated_raw:
        updated_raw["events"] = payload.events.to_dict()

    entry.raw_result = updated_raw


def _build_final_response(
    text: str,
    timestamp: TimestampInfo,
    *,
    regenerated: bool,
) -> AgentResponse | None:
    prepared = _prepare_agent_display_text(text)
    normalized = normalize_for_display(prepared)
    if not normalized and timestamp.missing:
        return None
    return AgentResponse(
        text=text,
        display_text=normalized,
        timestamp=timestamp,
        step_index=None,
        is_final=True,
        regenerated=regenerated,
    )


def _build_streamed_responses(
    trace: LlmTrace,
    final_response: AgentResponse | None,
    excluded_displays: set[str],
) -> tuple[tuple[AgentResponse, ...], TimestampInfo | None]:
    if not trace.steps:
        return (), None

    responses: list[AgentResponse] = []
    latest_timestamp: TimestampInfo | None = None

    for step in trace.steps:
        text = _extract_step_text(step)
        if not text:
            continue
        prepared = _prepare_agent_display_text(text)
        display_text = normalize_for_display(prepared)
        if display_text and display_text in excluded_displays:
            continue
        timestamp = _build_timestamp(step.occurred_at, source="llm_step")
        response = AgentResponse(
            text=text,
            display_text=display_text,
            timestamp=timestamp,
            step_index=step.index,
            is_final=False,
            regenerated=False,
        )
        responses.append(response)
        if not timestamp.missing:
            latest_timestamp = timestamp

    if latest_timestamp is None and responses:
        candidate = responses[-1].timestamp
        if not candidate.missing:
            latest_timestamp = candidate

    return tuple(responses), latest_timestamp


def _extract_step_text(step: LlmStep) -> str:
    content = step.response.get("content")
    if isinstance(content, str):
        return content.strip()
    return ""


def _build_tool_calls(
    entry_id: str,
    snapshots: Sequence[ToolResultSnapshot],
    trace: LlmTrace,
) -> tuple[tuple[ToolCallDetails, ...], TimestampInfo | None]:
    if not snapshots:
        return (), None

    ordered_snapshots = [
        snapshot
        for _, snapshot in sorted(
            enumerate(snapshots),
            key=lambda pair: (
                0 if pair[1].sequence is not None else 1,
                pair[1].sequence if pair[1].sequence is not None else pair[0],
            ),
        )
    ]

    summaries = summarize_tool_results(ordered_snapshots)
    summaries_by_id: dict[str, ToolCallSummary] = {}
    fallback_summaries: list[ToolCallSummary] = []
    for summary in summaries:
        raw_payload = summary.raw_payload
        call_id: str | None = None
        if isinstance(raw_payload, Mapping):
            call_id_value = raw_payload.get("call_id")
            if isinstance(call_id_value, str) and call_id_value.strip():
                call_id = call_id_value.strip()
        if call_id:
            summaries_by_id[call_id] = summary
        else:
            fallback_summaries.append(summary)

    tool_requests = _map_tool_requests(trace)
    tool_calls: list[ToolCallDetails] = []
    latest_timestamp: TimestampInfo | None = None

    fallback_iter = iter(fallback_summaries)

    for index, snapshot in enumerate(ordered_snapshots, start=1):
        summary = summaries_by_id.get(snapshot.call_id)
        if summary is None:
            summary_tuple = summarize_tool_results([snapshot])
            summary = summary_tuple[0] if summary_tuple else next(fallback_iter, None)
        if summary is None:
            summary = ToolCallSummary(
                index=index,
                tool_name=normalize_for_display(snapshot.tool_name or ""),
                status=normalize_for_display(""),
                bullet_lines=(),
            )
        else:
            summary = ToolCallSummary(
                index=index,
                tool_name=summary.tool_name,
                status=summary.status,
                bullet_lines=summary.bullet_lines,
                started_at=summary.started_at,
                completed_at=summary.completed_at,
                last_observed_at=summary.last_observed_at,
                raw_payload=summary.raw_payload,
                duration=summary.duration,
                cost=summary.cost,
                error_message=summary.error_message,
                arguments=summary.arguments,
            )

        raw_data_safe = history_json_safe(snapshot.to_dict())
        if isinstance(raw_data_safe, Mapping):
            raw_data = dict(raw_data_safe)
        else:
            raw_data = raw_data_safe

        request_payload = _tool_request_payload(tool_requests.get(snapshot.call_id))
        step_index_value: int | None = None
        if request_payload is not None:
            step_index_value = request_payload.get("step_index")
            if not isinstance(step_index_value, int):
                try:
                    step_index_value = int(step_index_value)
                except (TypeError, ValueError):
                    step_index_value = None
        raw_map: dict[str, Any] | None = None
        if isinstance(raw_data, Mapping):
            raw_map = dict(raw_data)

        if request_payload and raw_map is not None:
            raw_map.setdefault("llm_request", request_payload)
            response_payload = request_payload.get("response")
            if response_payload:
                raw_map.setdefault("llm_response", response_payload)

        if raw_map is not None:
            events_payload = raw_map.get("events")
            normalised_events: list[dict[str, Any]] = []
            if isinstance(events_payload, Sequence):
                for event in events_payload:
                    if isinstance(event, Mapping):
                        event_map = dict(event)
                        if (
                            event_map.get("kind") == "started"
                            and not event_map.get("message")
                        ):
                            event_map["message"] = "Applying updates"
                        normalised_events.append(event_map)

            if not normalised_events:
                started_at = raw_map.get("started_at") or snapshot.started_at
                completed_at = raw_map.get("completed_at") or snapshot.completed_at
                if started_at:
                    normalised_events.append(
                        {
                            "kind": "started",
                            "occurred_at": started_at,
                            "message": "Applying updates",
                        }
                    )
                if completed_at:
                    normalised_events.append(
                        {
                            "kind": "failed"
                            if snapshot.status == "failed"
                            else "completed",
                            "occurred_at": completed_at,
                        }
                    )

            if normalised_events:
                raw_map["events"] = normalised_events
            raw_data = raw_map
        timestamp = _tool_timestamp(snapshot)

        if not timestamp.missing:
            if latest_timestamp is None:
                latest_timestamp = timestamp
            elif (
                timestamp.occurred_at is not None
                and latest_timestamp.occurred_at is not None
                and timestamp.occurred_at >= latest_timestamp.occurred_at
            ):
                latest_timestamp = timestamp

        identifier = snapshot.call_id or f"{entry_id}:tool:{index}"
        tool_calls.append(
            ToolCallDetails(
                summary=summary,
                call_identifier=identifier,
                raw_data=raw_data,
                timestamp=timestamp,
                step_index=step_index_value,
                llm_request=request_payload,
            )
        )

    return tuple(tool_calls), latest_timestamp


def _tool_timestamp(snapshot: ToolResultSnapshot) -> TimestampInfo:
    for candidate in (
        snapshot.started_at,
        snapshot.last_observed_at,
        snapshot.completed_at,
    ):
        timestamp = _build_timestamp(candidate, source="tool_result")
        if not timestamp.missing:
            return timestamp

    if snapshot.events:
        for event in sorted(
            (event for event in snapshot.events if event.occurred_at),
            key=lambda item: item.occurred_at,
        ):
            timestamp = _build_timestamp(event.occurred_at, source="tool_result")
            if not timestamp.missing:
                return timestamp

    return _build_timestamp(None, source="tool_result")


def _map_tool_requests(trace: LlmTrace) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for step in trace.steps:
        tool_calls = step.response.get("tool_calls")
        if not isinstance(tool_calls, Sequence):
            continue
        for call in tool_calls:
            if not isinstance(call, Mapping):
                continue
            identifier = call.get("id") or call.get("call_id")
            if not identifier:
                continue
            identifier_text = str(identifier)
            payload = {
                "step_index": step.index,
                "occurred_at": step.occurred_at,
                "tool": call.get("name"),
                "arguments": call.get("arguments"),
                "messages": _sanitize_messages(step.request),
                "response": _sanitize_mapping(step.response),
            }
            sanitized = history_json_safe(payload)
            if isinstance(sanitized, Mapping):
                mapping[identifier_text] = dict(sanitized)
            else:
                mapping[identifier_text] = payload
    return mapping


def _tool_request_payload(info: dict[str, Any] | None) -> dict[str, Any] | None:
    if info is None:
        return None
    sanitized = history_json_safe(info)
    if isinstance(sanitized, Mapping):
        return dict(sanitized)
    return None


def _sanitize_messages(
    messages: Sequence[Mapping[str, Any]] | None,
) -> tuple[dict[str, Any], ...]:
    if not messages:
        return ()
    sanitized: list[dict[str, Any]] = []
    for message in messages:
        safe = history_json_safe(message)
        if isinstance(safe, Mapping):
            sanitized.append(dict(safe))
    return tuple(sanitized)


def _sanitize_mapping(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    safe = history_json_safe(value)
    if isinstance(safe, Mapping):
        return dict(safe)
    return None


def _build_llm_request_snapshot(trace: LlmTrace) -> LlmRequestSnapshot | None:
    if not trace.steps:
        return None
    sequence: list[dict[str, Any]] = []
    for step in trace.steps:
        sequence.append(
            {
                "step": step.index,
                "occurred_at": step.occurred_at,
                "messages": list(_sanitize_messages(step.request)),
            }
        )
    latest_messages = sequence[-1]["messages"] if sequence else []
    return LlmRequestSnapshot(
        messages=tuple(latest_messages),
        sequence=tuple(sequence) if sequence else None,
    )


def _build_agent_events(
    responses: tuple[AgentResponse, ...],
    final_response: AgentResponse | None,
    tool_calls: tuple[ToolCallDetails, ...],
    *,
    timeline: Sequence[AgentTimelineEntry] | None = None,
    timeline_status: str = "valid",
) -> tuple[AgentTimelineEvent, ...]:
    responses_by_index: dict[int, AgentResponse] = {}
    for response in responses:
        if response.step_index is not None:
            responses_by_index[response.step_index] = response

    tools_by_id: dict[str, ToolCallDetails] = {}
    for detail in tool_calls:
        if detail.call_identifier:
            tools_by_id[detail.call_identifier] = detail

    events: list[AgentTimelineEvent] = []

    if final_response is not None and final_response.step_index is not None:
        responses_by_index.setdefault(final_response.step_index, final_response)

    def _timestamp_with_fallback(
        current: TimestampInfo, *, occurred_at: str | None, source: str
    ) -> TimestampInfo:
        if current.missing and occurred_at:
            return _build_timestamp(occurred_at, source=source)
        return current

    if timeline and timeline_status == "valid":
        ordered_timeline = sorted(timeline, key=lambda entry: entry.sequence)
        seen_responses: set[int] = set()

        for _, entry in enumerate(ordered_timeline):
            occurred_at = entry.occurred_at
            if entry.kind == "llm_step":
                if entry.step_index is None:
                    continue
                response = responses_by_index.get(entry.step_index)
                if response is None:
                    continue
                response.timestamp = _timestamp_with_fallback(
                    response.timestamp, occurred_at=occurred_at, source="timeline"
                )
                events.append(
                    AgentTimelineEvent(
                        kind="response",
                        timestamp=response.timestamp,
                        order_index=entry.sequence,
                        sequence=entry.sequence,
                        response=response,
                    )
                )
                seen_responses.add(entry.step_index)
            elif entry.kind == "tool_call":
                tool_call = tools_by_id.get(entry.call_id or "")
                if tool_call is None:
                    continue
                if entry.step_index is not None:
                    tool_call.step_index = entry.step_index
                tool_call.timestamp = _timestamp_with_fallback(
                    tool_call.timestamp, occurred_at=occurred_at, source="timeline"
                )
                events.append(
                    AgentTimelineEvent(
                        kind="tool",
                        timestamp=tool_call.timestamp,
                        order_index=entry.sequence,
                        sequence=entry.sequence,
                        tool_call=tool_call,
                    )
                )
            elif entry.kind == "agent_finished" and final_response is not None:
                final_response.timestamp = _timestamp_with_fallback(
                    final_response.timestamp,
                    occurred_at=occurred_at,
                    source="timeline",
                )
                events.append(
                    AgentTimelineEvent(
                        kind="response",
                        timestamp=final_response.timestamp,
                        order_index=entry.sequence,
                        sequence=entry.sequence,
                        response=final_response,
                    )
                )
        return tuple(events)

    def _sort_key_for_timestamp(info: TimestampInfo) -> tuple[bool, str, str]:
        if info.occurred_at is not None:
            return (False, info.occurred_at.isoformat(), info.raw or "")
        if info.raw:
            return (False, "", info.raw)
        return (True, "", "")

    combined_events: list[tuple[tuple[Any, ...], AgentTimelineEvent]] = []
    seen_steps: set[int] = set()

    response_candidates: list[AgentResponse] = list(responses)
    if final_response is not None:
        response_candidates.append(final_response)

    primary_responses = [resp for resp in response_candidates if not resp.is_final]
    primary_responses.sort(
        key=lambda resp: (
            resp.step_index is None,
            resp.step_index if resp.step_index is not None else 0,
            _sort_key_for_timestamp(resp.timestamp),
        ),
    )
    final_responses = [resp for resp in response_candidates if resp.is_final]
    final_responses.sort(
        key=lambda resp: (
            resp.step_index is None,
            resp.step_index if resp.step_index is not None else 0,
            _sort_key_for_timestamp(resp.timestamp),
        ),
    )

    def _event_key(timestamp: TimestampInfo, kind_order: int, seq_hint: int) -> tuple[Any, ...]:
        ts_key = _sort_key_for_timestamp(timestamp)
        return (ts_key[0], ts_key[1], ts_key[2], kind_order, seq_hint)

    for response in primary_responses + final_responses:
        if (
            not response.is_final
            and response.step_index is not None
            and response.step_index in seen_steps
        ):
            continue
        if response.step_index is not None:
            seen_steps.add(response.step_index)
        combined_events.append(
            (
                _event_key(
                    response.timestamp,
                    0,
                    response.step_index if response.step_index is not None else -1,
                ),
                AgentTimelineEvent(
                    kind="response",
                    timestamp=response.timestamp,
                    order_index=0,
                    sequence=0,
                    response=response,
                ),
            )
        )

    ordered_tools = sorted(
        tool_calls,
        key=lambda call: (
            _sort_key_for_timestamp(call.timestamp),
            call.call_identifier or "",
        ),
    )
    for tool_call in ordered_tools:
        combined_events.append(
            (
                _event_key(
                    tool_call.timestamp,
                    1,
                    tool_call.summary.index if tool_call.summary.index is not None else -1,
                ),
                AgentTimelineEvent(
                    kind="tool",
                    timestamp=tool_call.timestamp,
                    order_index=0,
                    sequence=0,
                    tool_call=tool_call,
                ),
            )
        )

    combined_events.sort(key=lambda item: item[0])

    ordered_events: list[AgentTimelineEvent] = []
    for order_index, (_, event) in enumerate(combined_events):
        event.order_index = order_index
        event.sequence = order_index
        ordered_events.append(event)

    return tuple(ordered_events)


def agent_turn_event_signature(
    events: Sequence[AgentTimelineEvent],
) -> tuple[tuple[Any, ...], ...]:
    """Return a deterministic signature describing *events* order and identity."""

    signature: list[tuple[Any, ...]] = []
    for event in events:
        if event.kind == "response":
            step_index = None
            is_final: bool | None = None
            if event.response is not None:
                step_index = event.response.step_index
                is_final = event.response.is_final
            signature.append(
                (
                    "response",
                    event.sequence,
                    event.order_index,
                    step_index,
                    is_final,
                )
            )
        elif event.kind == "tool":
            call_identifier = None
            if event.tool_call is not None:
                call_identifier = event.tool_call.call_identifier
            signature.append(
                (
                    "tool",
                    event.sequence,
                    event.order_index,
                    call_identifier,
                )
            )
    return tuple(signature)


def _timeline_timestamp(
    timeline_entries: Sequence[AgentTimelineEntry],
) -> TimestampInfo:
    for entry in sorted(
        (item for item in timeline_entries if item.occurred_at),
        key=lambda item: item.sequence if item.sequence is not None else -1,
        reverse=True,
    ):
        return _build_timestamp(entry.occurred_at, source="timeline")
    return _build_timestamp(None, source="timeline")


def _event_log_timestamp(event_log: AgentEventLog) -> TimestampInfo:
    for event in reversed(event_log.events):
        if event.occurred_at:
            return _build_timestamp(event.occurred_at, source="event_log")
    return _build_timestamp(None, source="event_log")


def _llm_trace_timestamp(trace: LlmTrace) -> TimestampInfo:
    if trace.steps:
        for step in reversed(trace.steps):
            timestamp = _build_timestamp(step.occurred_at, source="llm_trace")
            if not timestamp.missing:
                return timestamp
    return _build_timestamp(None, source="llm_trace")


def _resolve_turn_timestamp(
    primary: TimestampInfo,
    prompt_timestamp: TimestampInfo,
    *,
    timeline_timestamp: TimestampInfo,
    event_log_timestamp: TimestampInfo,
    llm_trace_timestamp: TimestampInfo,
) -> TimestampInfo:
    for candidate in (
        timeline_timestamp,
        event_log_timestamp,
        primary,
        llm_trace_timestamp,
        prompt_timestamp,
    ):
        if not candidate.missing:
            return candidate
    return primary


def _build_transcript_entry(
    conversation: ChatConversation,
    entry_index: int,
    entry: ChatEntry,
) -> TranscriptEntry:
    entry_id = f"{conversation.conversation_id}:{entry_index}"
    prompt = _build_prompt(entry)
    context_messages = _build_context_messages(entry)
    agent_turn = _build_agent_turn(entry_id, entry_index, entry)
    layout_hints = dict(entry.layout_hints or {})
    can_regenerate = _can_regenerate_entry(
        entry_index, len(conversation.entries), entry
    )
    return TranscriptEntry(
        entry_id=entry_id,
        entry_index=entry_index,
        entry=entry,
        prompt=prompt,
        context_messages=context_messages,
        agent_turn=agent_turn,
        system_messages=(),
        layout_hints=layout_hints,
        can_regenerate=can_regenerate,
    )


def build_conversation_timeline(
    conversation: ChatConversation,
) -> ConversationTimeline:
    entries: list[TranscriptEntry] = []
    for entry_index, entry in enumerate(conversation.entries):
        entries.append(_build_transcript_entry(conversation, entry_index, entry))
    return ConversationTimeline(
        conversation_id=conversation.conversation_id,
        entries=tuple(entries),
    )


def build_entry_segments(entry: TranscriptEntry) -> tuple[TranscriptSegment, ...]:
    entry_id = entry.entry_id
    entry_index = entry.entry_index
    layout_hints = dict(entry.layout_hints)
    segments: list[TranscriptSegment] = []

    if entry.prompt is not None or entry.context_messages:
        payload = PromptSegment(
            prompt=entry.prompt,
            context_messages=entry.context_messages,
            layout_hints=dict(layout_hints),
        )
        segments.append(
            TranscriptSegment(
                segment_id=f"{entry_id}:user",
                entry_id=entry_id,
                entry_index=entry_index,
                kind="user",
                payload=payload,
            )
        )

    if entry.agent_turn is not None or entry.can_regenerate or entry.system_messages:
        payload = AgentSegment(
            turn=entry.agent_turn,
            layout_hints=dict(layout_hints),
            can_regenerate=entry.can_regenerate,
        )
        segments.append(
            TranscriptSegment(
                segment_id=f"{entry_id}:agent",
                entry_id=entry_id,
                entry_index=entry_index,
                kind="agent",
                payload=payload,
            )
        )

    for index, system_event in enumerate(entry.system_messages, start=1):
        segments.append(
            TranscriptSegment(
                segment_id=f"{entry_id}:system:{index}",
                entry_id=entry_id,
                entry_index=entry_index,
                kind="system",
                payload=system_event,
            )
        )

    return tuple(segments)


def build_transcript_segments(conversation: ChatConversation) -> TranscriptSegments:
    timeline = build_conversation_timeline(conversation)
    segments: list[TranscriptSegment] = []
    entry_order: list[str] = []

    for timeline_entry in timeline.entries:
        entry_order.append(timeline_entry.entry_id)
        segments.extend(build_entry_segments(timeline_entry))

    return TranscriptSegments(
        conversation_id=timeline.conversation_id,
        entry_order=tuple(entry_order),
        segments=tuple(segments),
    )


def _capture_entry_fingerprints(
    entries: Sequence[TranscriptEntry],
) -> dict[str, tuple[Any, ...] | None]:
    fingerprints: dict[str, tuple[Any, ...] | None] = {}
    for entry in entries:
        agent_turn = entry.agent_turn
        fingerprint = (
            agent_turn.timeline_fingerprint if agent_turn is not None else None
        )
        fingerprints[entry.entry_id] = fingerprint
    return fingerprints


class ConversationTimelineCache:
    """Incrementally rebuild :class:`ConversationTimeline` instances."""

    def __init__(self) -> None:
        self._cache: dict[str, _CachedTimeline] = {}
        self._dirty_entries: dict[str, set[str]] = {}
        self._full_invalidations: set[str] = set()

    def invalidate_conversation(self, conversation_id: str | None) -> None:
        if conversation_id:
            self._full_invalidations.add(conversation_id)

    def invalidate_entries(
        self, conversation_id: str | None, entry_ids: Iterable[str]
    ) -> None:
        if not conversation_id:
            return
        pending = self._dirty_entries.setdefault(conversation_id, set())
        for entry_id in entry_ids:
            if entry_id:
                pending.add(entry_id)

    def forget(self, conversation_id: str) -> None:
        self._cache.pop(conversation_id, None)
        self._dirty_entries.pop(conversation_id, None)
        self._full_invalidations.discard(conversation_id)

    def peek(self, conversation_id: str) -> ConversationTimeline | None:
        cached = self._cache.get(conversation_id)
        return cached.timeline if cached is not None else None

    def timeline_for(self, conversation: ChatConversation) -> ConversationTimeline:
        conversation_id = conversation.conversation_id
        cached = self._cache.get(conversation_id)
        dirty_entries = self._dirty_entries.pop(conversation_id, set())
        requires_full_refresh = (
            cached is None
            or conversation_id in self._full_invalidations
            or len(conversation.entries) < len(cached.timeline.entries)
        )

        entry_fingerprints: dict[str, tuple[Any, ...] | None] = (
            dict(cached.entry_fingerprints) if cached is not None else {}
        )

        if requires_full_refresh:
            entries: list[TranscriptEntry] = []
            for entry_index, entry in enumerate(conversation.entries):
                entries.append(
                    _build_transcript_entry(conversation, entry_index, entry)
                )
            timeline = ConversationTimeline(
                conversation_id=conversation.conversation_id,
                entries=tuple(entries),
            )
            self._cache[conversation_id] = _CachedTimeline(
                timeline=timeline,
                entry_map={entry.entry_id: entry for entry in timeline.entries},
                entry_fingerprints=_capture_entry_fingerprints(timeline.entries),
            )
            self._full_invalidations.discard(conversation_id)
            return timeline

        entries = list(cached.timeline.entries)
        entry_map = dict(cached.entry_map)
        updated = False

        cached_entry_count = len(entries)
        current_entry_count = len(conversation.entries)
        if current_entry_count > cached_entry_count:
            for entry_index in range(cached_entry_count, current_entry_count):
                rebuilt = _build_transcript_entry(
                    conversation, entry_index, conversation.entries[entry_index]
                )
                entries.append(rebuilt)
                entry_map[rebuilt.entry_id] = rebuilt
                entry_fingerprints[rebuilt.entry_id] = (
                    rebuilt.agent_turn.timeline_fingerprint
                    if rebuilt.agent_turn is not None
                    else None
                )
            updated = True

        if not dirty_entries and not updated:
            for entry_index, entry in enumerate(conversation.entries):
                entry_id = f"{conversation_id}:{entry_index}"
                cached_fingerprint = entry_fingerprints.get(entry_id)
                current_fingerprint = _agent_timeline_fingerprint_for_entry(entry)
                if cached_fingerprint != current_fingerprint:
                    dirty_entries.add(entry_id)

            if not dirty_entries:
                self._full_invalidations.discard(conversation_id)
                return cached.timeline

        for entry_id in dirty_entries:
            index = _resolve_entry_index(conversation_id, entry_id)
            if index is None or index >= len(conversation.entries):
                continue
            rebuilt = _build_transcript_entry(
                conversation, index, conversation.entries[index]
            )
            entries[index] = rebuilt
            entry_map[entry_id] = rebuilt
            entry_fingerprints[entry_id] = (
                rebuilt.agent_turn.timeline_fingerprint
                if rebuilt.agent_turn is not None
                else None
            )
            updated = True

        if updated:
            timeline = ConversationTimeline(
                conversation_id=conversation.conversation_id,
                entries=tuple(entries),
            )
            self._cache[conversation_id] = _CachedTimeline(
                timeline=timeline,
                entry_map=entry_map,
                entry_fingerprints=entry_fingerprints,
            )
            self._full_invalidations.discard(conversation_id)
            return timeline

        self._full_invalidations.discard(conversation_id)
        return cached.timeline


def _resolve_entry_index(conversation_id: str, entry_id: str) -> int | None:
    prefix = f"{conversation_id}:"
    if not entry_id.startswith(prefix):
        return None
    index_raw = entry_id[len(prefix) :]
    try:
        return int(index_raw)
    except (TypeError, ValueError):
        return None


def _can_regenerate_entry(
    entry_index: int,
    total_entries: int,
    entry: ChatEntry,
) -> bool:
    is_last_entry = entry_index == total_entries - 1
    if not is_last_entry:
        return False

    # ``response_at`` is the primary indicator that the agent finished.
    if getattr(entry, "response_at", None):
        return True

    # In failure paths some history items were saved without timestamps,
    # but still carry diagnostic or raw payload data. Treat those as
    # completed runs so that the "Regenerate" control is available.
    if getattr(entry, "raw_result", None) is not None:
        return True

    if getattr(entry, "diagnostic", None) is not None:
        return True

    return False


__all__ = [
    "TimestampInfo",
    "PromptMessage",
    "AgentResponse",
    "AgentTimelineEvent",
    "LlmRequestSnapshot",
    "ToolCallDetails",
    "AgentTurn",
    "SystemMessage",
    "TranscriptEntry",
    "ConversationTimeline",
    "PromptSegment",
    "AgentSegment",
    "TranscriptSegment",
    "TranscriptSegments",
    "build_entry_segments",
    "build_conversation_timeline",
    "build_transcript_segments",
    "ConversationTimelineCache",
    "agent_turn_event_signature",
]
