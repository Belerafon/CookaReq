"""Turn-oriented view model for the agent chat transcript."""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from collections.abc import Iterable, Mapping, Sequence
import re
from typing import Any, Literal, TYPE_CHECKING

from ...agent.run_contract import AgentRunPayload, LlmTrace, LlmStep, ToolResultSnapshot
from ..text import normalize_for_display
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
    llm_request: LlmRequestSnapshot | None
    tool_calls: tuple[ToolCallDetails, ...]
    raw_payload: Any | None
    events: tuple[AgentTimelineEvent, ...]


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


def _build_agent_turn(
    entry_id: str,
    entry_index: int,
    entry: ChatEntry,
) -> AgentTurn | None:
    response_timestamp = _build_timestamp(entry.response_at, source="response_at")
    prompt_timestamp = _build_timestamp(entry.prompt_at, source="prompt_at")

    raw_result = entry.raw_result if isinstance(entry.raw_result, Mapping) else None
    payload = agent_payload_from_mapping(raw_result)
    if payload is None:
        tool_snapshots = tool_snapshots_from(entry.tool_results)
        reasoning_source = entry.reasoning
        llm_trace = LlmTrace()
        final_text = entry.display_response or entry.response or ""
    else:
        tool_snapshots = payload.tool_results
        reasoning_source = payload.reasoning
        llm_trace = payload.llm_trace
        final_text = (
            entry.display_response or payload.result_text or entry.response or ""
        )

    raw_payload = entry.history_safe_raw_result()
    reasoning_segments = entry.cache_view_value(
        "reasoning_segments",
        lambda: _sanitize_mapping_sequence(reasoning_source),
    )

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

    excluded_displays: set[str] = set()
    if reasoning_display:
        excluded_displays.add(reasoning_display)
    if final_response is not None:
        final_display = final_response.display_text or ""
        if reasoning_display:
            if final_display == reasoning_display:
                final_response = None
            elif final_display:
                excluded_displays.add(final_display)
        elif final_display:
            excluded_displays.add(final_display)

    streamed_responses, latest_stream_timestamp = _build_streamed_responses(
        llm_trace,
        final_response,
        excluded_displays,
    )
    tool_calls, latest_tool_timestamp = _build_tool_calls(
        entry_id, tool_snapshots, llm_trace
    )
    events = _build_agent_events(streamed_responses, final_response, tool_calls)

    resolved_timestamp = _resolve_turn_timestamp(
        response_timestamp,
        events,
        prompt_timestamp,
    )
    if final_response is not None and final_response.timestamp.missing:
        final_response.timestamp = resolved_timestamp

    occurred_at = resolved_timestamp.occurred_at
    llm_request = _build_llm_request_snapshot(llm_trace)

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
        llm_request=llm_request,
        tool_calls=tool_calls,
        raw_payload=raw_payload,
        events=events,
    )


def _prepare_agent_display_text(value: str | None) -> str:
    if not value:
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = _BR_TAG_PATTERN.sub("  \n", text)
    text = _SPACE_RUN_PATTERN.sub(" ", text)
    return text.strip(" \t\f\v")


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

    summaries = summarize_tool_results(snapshots)
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

    for index, snapshot in enumerate(snapshots, start=1):
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

        tool_calls.append(
            ToolCallDetails(
                summary=summary,
                call_identifier=snapshot.call_id or None,
                raw_data=raw_data,
                timestamp=timestamp,
                llm_request=request_payload,
            )
        )

    return tuple(tool_calls), latest_timestamp


def _tool_timestamp(snapshot: ToolResultSnapshot) -> TimestampInfo:
    for candidate in (snapshot.completed_at, snapshot.last_observed_at, snapshot.started_at):
        timestamp = _build_timestamp(candidate, source="tool_result")
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
) -> tuple[AgentTimelineEvent, ...]:
    events: list[AgentTimelineEvent] = []
    order = 0

    for response in responses:
        events.append(
            AgentTimelineEvent(
                kind="response",
                timestamp=response.timestamp,
                order_index=order,
                response=response,
            )
        )
        order += 1

    if final_response is not None:
        events.append(
            AgentTimelineEvent(
                kind="response",
                timestamp=final_response.timestamp,
                order_index=order,
                response=final_response,
            )
        )
        order += 1

    for detail in tool_calls:
        events.append(
            AgentTimelineEvent(
                kind="tool",
                timestamp=detail.timestamp,
                order_index=order,
                tool_call=detail,
            )
        )
        order += 1

    events.sort(key=_event_sort_key)
    for index, event in enumerate(events):
        event.order_index = index
    return tuple(events)


def _event_sort_key(event: AgentTimelineEvent) -> tuple[int, _dt.datetime, int]:
    timestamp = event.timestamp.occurred_at
    if timestamp is None:
        return (1, _UTC_MIN, event.order_index)
    return (0, timestamp, event.order_index)


def _resolve_turn_timestamp(
    primary: TimestampInfo,
    events: Sequence[AgentTimelineEvent],
    prompt_timestamp: TimestampInfo,
) -> TimestampInfo:
    if not primary.missing:
        return primary
    for event in events:
        if not event.timestamp.missing:
            return event.timestamp
    if not prompt_timestamp.missing:
        return prompt_timestamp
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
            or len(cached.timeline.entries) != len(conversation.entries)
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
            )
            self._full_invalidations.discard(conversation_id)
            return timeline

        if not dirty_entries:
            self._full_invalidations.discard(conversation_id)
            return cached.timeline

        entries = list(cached.timeline.entries)
        entry_map = dict(cached.entry_map)
        updated = False

        for entry_id in dirty_entries:
            index = _resolve_entry_index(conversation_id, entry_id)
            if index is None or index >= len(conversation.entries):
                continue
            rebuilt = _build_transcript_entry(
                conversation, index, conversation.entries[index]
            )
            entries[index] = rebuilt
            entry_map[entry_id] = rebuilt
            updated = True

        if updated:
            timeline = ConversationTimeline(
                conversation_id=conversation.conversation_id,
                entries=tuple(entries),
            )
            self._cache[conversation_id] = _CachedTimeline(
                timeline=timeline,
                entry_map=entry_map,
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
    has_response = bool(entry.response_at)
    return is_last_entry and has_response


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
]
