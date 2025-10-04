"""Turn-oriented view model for the agent chat transcript."""

from __future__ import annotations

import datetime as _dt
import json
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any, Iterable, Literal, Mapping, Sequence

from ...llm.spec import SYSTEM_PROMPT
from ..chat_entry import ChatConversation, ChatEntry
from .history_utils import history_json_safe, normalise_tool_payloads
from .time_formatting import format_entry_timestamp, parse_iso_timestamp
from .tool_summaries import ToolCallSummary, summarize_tool_payload


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


def _resolve_entry_index(conversation_id: str, entry_id: str) -> int | None:
    prefix = f"{conversation_id}:"
    if not entry_id.startswith(prefix):
        return None
    index_raw = entry_id[len(prefix) :]
    try:
        return int(index_raw)
    except (TypeError, ValueError):
        return None


class ConversationTimelineCache:
    """Incrementally rebuild :class:`ConversationTimeline` instances."""

    def __init__(self) -> None:
        self._cache: dict[str, _CachedTimeline] = {}
        self._dirty_entries: dict[str, set[str]] = {}
        self._full_invalidations: set[str] = set()

    # ------------------------------------------------------------------
    def invalidate_conversation(self, conversation_id: str | None) -> None:
        if conversation_id:
            self._full_invalidations.add(conversation_id)

    # ------------------------------------------------------------------
    def invalidate_entries(
        self, conversation_id: str | None, entry_ids: Iterable[str]
    ) -> None:
        if not conversation_id:
            return
        pending = self._dirty_entries.setdefault(conversation_id, set())
        for entry_id in entry_ids:
            if entry_id:
                pending.add(entry_id)

    # ------------------------------------------------------------------
    def forget(self, conversation_id: str) -> None:
        self._cache.pop(conversation_id, None)
        self._dirty_entries.pop(conversation_id, None)
        self._full_invalidations.discard(conversation_id)

    # ------------------------------------------------------------------
    def peek(self, conversation_id: str) -> ConversationTimeline | None:
        cached = self._cache.get(conversation_id)
        return cached.timeline if cached is not None else None

    # ------------------------------------------------------------------
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
            timeline = build_conversation_timeline(conversation)
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
        fallback_to_full = False

        for entry_id in dirty_entries:
            index = _resolve_entry_index(conversation_id, entry_id)
            if index is None or index >= len(conversation.entries):
                fallback_to_full = True
                break
            entry = conversation.entries[index]
            rebuilt = _build_transcript_entry(conversation, index, entry)
            if rebuilt.entry_id != entry_id:
                fallback_to_full = True
                break
            if entry_map.get(entry_id) == rebuilt:
                continue
            entries[index] = rebuilt
            entry_map[entry_id] = rebuilt
            updated = True

        if fallback_to_full:
            timeline = build_conversation_timeline(conversation)
            self._cache[conversation_id] = _CachedTimeline(
                timeline=timeline,
                entry_map={entry.entry_id: entry for entry in timeline.entries},
            )
            self._full_invalidations.discard(conversation_id)
            return timeline

        if updated:
            timeline = ConversationTimeline(
                conversation_id=conversation_id,
                entries=tuple(entries),
            )
            cached.timeline = timeline
            cached.entry_map = entry_map
        else:
            timeline = cached.timeline

        self._full_invalidations.discard(conversation_id)
        return timeline


def _build_transcript_entry(
    conversation: ChatConversation,
    entry_index: int,
    entry: ChatEntry,
) -> TranscriptEntry:
    entry_id = f"{conversation.conversation_id}:{entry_index}"
    prompt = _build_prompt(entry)
    context_messages = _build_context_messages(entry)
    agent_turn = _build_agent_turn(entry_id, entry_index, entry)
    layout_hints = _sanitize_layout_hints(entry.layout_hints)
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
    """Return turn-oriented timeline for *conversation*."""

    entries: list[TranscriptEntry] = []

    for entry_index, entry in enumerate(conversation.entries):
        entries.append(_build_transcript_entry(conversation, entry_index, entry))

    return ConversationTimeline(
        conversation_id=conversation.conversation_id,
        entries=tuple(entries),
    )


def build_entry_segments(entry: TranscriptEntry) -> tuple[TranscriptSegment, ...]:
    """Return ordered segments for a single *entry*."""

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
    """Flatten *conversation* into ordered transcript segments."""

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


# ---------------------------------------------------------------------------
def _build_prompt(entry: ChatEntry) -> PromptMessage | None:
    text = entry.prompt or ""
    timestamp = _build_timestamp(entry.prompt_at, source="prompt_at")
    if not text and not timestamp.raw:
        # Prompt is empty and no timestamp has been recorded; skip placeholder.
        return None
    return PromptMessage(text=text, timestamp=timestamp)


def _build_context_messages(entry: ChatEntry) -> tuple[dict[str, Any], ...]:
    messages_raw = entry.context_messages or _extract_request_context(entry)
    if not messages_raw:
        return ()
    messages: list[dict[str, Any]] = []
    for message in messages_raw:
        if isinstance(message, Mapping):
            safe_message = history_json_safe(message)
            if isinstance(safe_message, Mapping):
                messages.append(dict(safe_message))
    return tuple(messages)


def _build_agent_turn(
    entry_id: str,
    entry_index: int,
    entry: ChatEntry,
) -> AgentTurn | None:
    timestamp = _build_timestamp(entry.response_at, source="response_at")
    final_response = _build_final_response(entry, timestamp)
    streamed_responses, latest_stream_timestamp = _build_streamed_responses(
        entry, final_response
    )
    reasoning_segments = _sanitize_reasoning_segments(entry.reasoning)
    llm_request = _build_llm_request_snapshot(entry)
    tool_calls, latest_tool_timestamp = _build_tool_calls(
        entry_id, entry_index, entry
    )
    raw_payload = history_json_safe(entry.raw_result)

    if final_response is None and streamed_responses:
        promoted = streamed_responses[-1]
        promoted_timestamp = promoted.timestamp
        if promoted_timestamp.missing:
            promoted_timestamp = latest_stream_timestamp or timestamp
        final_response = AgentResponse(
            text=promoted.text,
            display_text=promoted.display_text,
            timestamp=promoted_timestamp,
            step_index=None,
            is_final=True,
            regenerated=bool(getattr(entry, "regenerated", False)),
        )
        streamed_responses = streamed_responses[:-1]
        latest_stream_timestamp = promoted_timestamp

    if timestamp.missing:
        timestamp = _resolve_turn_timestamp(
            timestamp,
            final_response=final_response,
            stream_timestamp=latest_stream_timestamp,
            tool_timestamp=latest_tool_timestamp,
            prompt_timestamp=_build_timestamp(entry.prompt_at, source="prompt_at"),
        )
        if final_response is not None:
            final_response.timestamp = timestamp

    has_content = bool(
        final_response
        or streamed_responses
        or reasoning_segments
        or (llm_request and llm_request.messages)
        or tool_calls
        or raw_payload is not None
    )

    if not has_content and not timestamp.raw:
        return None

    events = _build_agent_events(
        timestamp,
        streamed_responses,
        final_response,
        tool_calls,
    )

    return AgentTurn(
        entry_id=entry_id,
        entry_index=entry_index,
        occurred_at=timestamp.occurred_at,
        timestamp=timestamp,
        streamed_responses=streamed_responses,
        final_response=final_response,
        reasoning=reasoning_segments,
        llm_request=llm_request,
        tool_calls=tool_calls,
        raw_payload=raw_payload,
        events=events,
    )


def _build_final_response(
    entry: ChatEntry, timestamp: TimestampInfo
) -> AgentResponse | None:
    text = entry.response or ""
    display_text = entry.display_response or text
    if not text and not display_text:
        return None
    return AgentResponse(
        text=text,
        display_text=display_text,
        timestamp=timestamp,
        step_index=None,
        is_final=True,
        regenerated=bool(getattr(entry, "regenerated", False)),
    )


def _build_streamed_responses(
    entry: ChatEntry, final_response: AgentResponse | None
) -> tuple[tuple[AgentResponse, ...], TimestampInfo | None]:
    payloads = _collect_llm_step_payloads(entry)
    if not payloads:
        return (), None

    final_text = _normalise_message_text(
        final_response.display_text if final_response else None
    )

    responses: list[AgentResponse] = []
    fallback_index = 1
    latest_timestamp: TimestampInfo | None = None
    for payload in payloads:
        response = _build_stream_step_response(payload, fallback_index)
        if response is None:
            continue
        fallback_index = (response.step_index or fallback_index) + 1
        if final_text and _normalise_message_text(response.display_text) == final_text:
            continue
        responses.append(response)
        if not response.timestamp.missing:
            if latest_timestamp is None:
                latest_timestamp = response.timestamp
            elif (
                response.timestamp.occurred_at
                and latest_timestamp.occurred_at
                and response.timestamp.occurred_at
                >= latest_timestamp.occurred_at
            ):
                latest_timestamp = response.timestamp
    if latest_timestamp is None and responses:
        candidate = responses[-1].timestamp
        if not candidate.missing:
            latest_timestamp = candidate
    return tuple(responses), latest_timestamp


def _build_stream_step_response(
    payload: Mapping[str, Any], fallback_index: int
) -> AgentResponse | None:
    if not isinstance(payload, Mapping):
        return None
    response_payload = payload.get("response")
    if not isinstance(response_payload, Mapping):
        return None
    content_value = response_payload.get("content")
    if not isinstance(content_value, str):
        return None
    text = content_value.strip()
    if not text:
        return None

    timestamp_raw = response_payload.get("timestamp")
    timestamp_value = (
        timestamp_raw.strip()
        if isinstance(timestamp_raw, str) and timestamp_raw.strip()
        else None
    )
    timestamp = _build_timestamp(timestamp_value, source="llm_step")

    step_index: int | None = None
    step_value = payload.get("step")
    if isinstance(step_value, (int, float)):
        step_index = int(step_value)
    elif isinstance(step_value, str):
        with suppress(ValueError):
            step_index = int(step_value.strip())
    if step_index is None:
        step_index = fallback_index

    return AgentResponse(
        text=text,
        display_text=text,
        timestamp=timestamp,
        step_index=step_index,
        is_final=False,
        regenerated=False,
    )


def _sanitize_reasoning_segments(
    segments_raw: Sequence[dict[str, Any]] | None,
) -> tuple[dict[str, Any], ...]:
    if not segments_raw:
        return ()
    segments: list[dict[str, Any]] = []
    for segment in segments_raw:
        if not isinstance(segment, Mapping):
            continue
        safe_segment = history_json_safe(segment)
        if isinstance(safe_segment, Mapping):
            segments.append(dict(safe_segment))
    return tuple(segments)


def _build_llm_request_snapshot(
    entry: ChatEntry,
) -> LlmRequestSnapshot | None:
    messages, sequence = _extract_llm_request_details(entry)
    if not messages:
        return None
    return LlmRequestSnapshot(messages=messages, sequence=sequence)


def _build_tool_calls(
    entry_id: str,
    entry_index: int,
    entry: ChatEntry,
) -> tuple[tuple[ToolCallDetails, ...], TimestampInfo | None]:
    payloads = _iter_tool_payloads(entry.raw_result)
    if not payloads:
        return (), None

    raw_records = _collect_llm_tool_requests(entry)
    tool_calls: list[ToolCallDetails] = []
    latest_timestamp: TimestampInfo | None = None
    for tool_index, payload in enumerate(payloads, start=1):
        summary = summarize_tool_payload(tool_index, payload)
        safe_payload = history_json_safe(payload)
        if summary is None:
            summary = ToolCallSummary(
                index=tool_index,
                tool_name="",
                status="",
                bullet_lines=(),
                raw_payload=safe_payload,
            )
        else:
            summary = replace(summary, raw_payload=safe_payload)

        call_identifier = _extract_tool_identifier(payload)
        raw_snapshot: Mapping[str, Any] | None = None
        if call_identifier is not None:
            raw_snapshot = raw_records.get(call_identifier)
        if raw_snapshot is None:
            raw_snapshot = raw_records.get(str(tool_index))

        safe_snapshot: Mapping[str, Any] | None = None
        if isinstance(raw_snapshot, Mapping):
            snapshot_candidate = history_json_safe(raw_snapshot)
            if isinstance(snapshot_candidate, Mapping):
                safe_snapshot = dict(snapshot_candidate)

        condensed_raw_source = safe_snapshot or raw_snapshot
        condensed_raw = _compose_tool_raw_data(condensed_raw_source)

        raw_sections: dict[str, Any] = {}
        if isinstance(condensed_raw, Mapping):
            raw_sections.update(condensed_raw)

        tool_result_section: Mapping[str, Any] | None = None
        if isinstance(safe_payload, Mapping):
            tool_result_section = _compose_tool_result_section(safe_payload)
        if tool_result_section is not None:
            raw_sections["tool_result"] = tool_result_section

        if raw_sections:
            deduplicated_sections = _deduplicate_tool_raw_sections(raw_sections)
            condensed_candidate = history_json_safe(deduplicated_sections)
            if isinstance(condensed_candidate, Mapping):
                condensed_raw = dict(condensed_candidate)
            else:
                condensed_raw = None
        else:
            condensed_raw = None

        llm_request = _extract_tool_llm_request(condensed_raw, safe_snapshot)

        call_timestamp_raw = _extract_tool_timestamp(payload)
        if call_timestamp_raw:
            candidate = _build_timestamp(call_timestamp_raw, source="tool_result")
            if not candidate.missing:
                if latest_timestamp is None:
                    latest_timestamp = candidate
                elif (
                    candidate.occurred_at
                    and latest_timestamp.occurred_at
                    and candidate.occurred_at >= latest_timestamp.occurred_at
                ):
                    latest_timestamp = candidate
            timestamp_info = candidate
        else:
            timestamp_info = _build_timestamp(None, source="tool_result")

        tool_calls.append(
            ToolCallDetails(
                summary=summary,
                call_identifier=call_identifier,
                raw_data=condensed_raw,
                timestamp=timestamp_info,
                llm_request=llm_request,
            )
        )
    return tuple(tool_calls), latest_timestamp


def _compose_tool_raw_data(raw_snapshot: Any) -> Mapping[str, Any] | None:
    """Prepare JSON-safe raw sections for a tool call."""

    if not isinstance(raw_snapshot, Mapping):
        return None

    sections: dict[str, Any] = {}

    for key in ("llm_request", "llm_response", "llm_error", "step"):
        if key not in raw_snapshot:
            continue
        candidate = history_json_safe(raw_snapshot.get(key))
        if _has_meaningful_payload(candidate):
            sections[key] = candidate

    diagnostics_payload = raw_snapshot.get("diagnostics")
    if isinstance(diagnostics_payload, Mapping):
        diagnostics_section: dict[str, Any] = {}
        for diag_key, value in diagnostics_payload.items():
            candidate = history_json_safe(value)
            if _has_meaningful_payload(candidate):
                diagnostics_section[diag_key] = candidate
        if diagnostics_section:
            sections["diagnostics"] = diagnostics_section

    return sections or None


def _extract_tool_llm_request(
    sections: Mapping[str, Any] | None,
    snapshot: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Return a JSON-safe LLM request payload for a tool call."""

    for source in (sections, snapshot):
        if not isinstance(source, Mapping):
            continue
        request_payload = source.get("llm_request")
        if not isinstance(request_payload, Mapping):
            continue
        safe_payload = history_json_safe(request_payload)
        if isinstance(safe_payload, Mapping) and safe_payload:
            return dict(safe_payload)
    return None


def _compose_tool_result_section(tool_payload: Any) -> Mapping[str, Any] | None:
    if not isinstance(tool_payload, Mapping):
        return None

    safe_payload = history_json_safe(tool_payload)
    if not isinstance(safe_payload, Mapping):
        return None

    sections: dict[str, Any] = {}

    tool_section: dict[str, Any] = {}
    name = _normalise_optional_string(
        safe_payload.get("tool_name")
        or safe_payload.get("tool")
        or safe_payload.get("name")
    )
    if name:
        tool_section["name"] = name

    identifiers: list[str] = []
    for key in ("tool_call_id", "call_id", "call_identifier"):
        identifier = _normalise_optional_string(safe_payload.get(key))
        if identifier and identifier not in identifiers:
            identifiers.append(identifier)
    if identifiers:
        if len(identifiers) == 1:
            tool_section["call_id"] = identifiers[0]
        else:
            tool_section["call_ids"] = identifiers

    for key in ("tool_arguments", "arguments", "args"):
        candidate = history_json_safe(safe_payload.get(key))
        if isinstance(candidate, Mapping) and _has_meaningful_payload(candidate):
            tool_section["arguments"] = candidate
            break

    if tool_section:
        sections["tool"] = tool_section

    status_section: dict[str, Any] = {}
    agent_status = _normalise_optional_string(
        safe_payload.get("agent_status") or safe_payload.get("status")
    )
    if agent_status:
        status_section["state"] = agent_status
    if "ok" in safe_payload:
        ok_value = history_json_safe(safe_payload.get("ok"))
        if _has_meaningful_payload(ok_value) or ok_value is False:
            status_section["ok"] = ok_value
    stop_reason = history_json_safe(safe_payload.get("agent_stop_reason"))
    if _has_meaningful_payload(stop_reason):
        status_section["stop_reason"] = stop_reason
    if status_section:
        sections["status"] = status_section

    status_updates = history_json_safe(safe_payload.get("status_updates"))
    if _has_meaningful_payload(status_updates):
        sections["status_updates"] = status_updates

    error_payload = history_json_safe(safe_payload.get("error"))
    if _has_meaningful_payload(error_payload):
        sections["error"] = error_payload

    result_payload = history_json_safe(safe_payload.get("result"))
    if _has_meaningful_payload(result_payload):
        sections["result"] = result_payload

    context_section: dict[str, Any] = {}
    for key in ("message_preview", "response_snapshot", "reasoning"):
        candidate = history_json_safe(safe_payload.get(key))
        if _has_meaningful_payload(candidate):
            context_section[key] = candidate
    if context_section:
        sections["context"] = context_section

    timeline = _collect_unique_timestamps(safe_payload)
    if timeline:
        if len(timeline) == 1:
            sections["timestamp"] = timeline[0][1]
        else:
            sections["timeline"] = {key: value for key, value in timeline}

    return sections or None


def _deduplicate_tool_raw_sections(sections: Mapping[str, Any]) -> dict[str, Any]:
    """Remove repeated tool arguments while keeping the richest snapshot."""

    if not isinstance(sections, Mapping):
        return {}

    working: dict[str, Any] = dict(sections)
    primary_location, canonical_arguments = _select_primary_tool_arguments(working)
    if canonical_arguments is None or primary_location is None:
        return working

    def _matches(value: Any) -> bool:
        return value == canonical_arguments

    retain_locations: set[tuple[Any, ...]] = set()
    if primary_location is not None:
        retain_locations.add(primary_location)

    request_location = ("llm_request", "arguments")
    request_section = working.get("llm_request")
    if isinstance(request_section, Mapping):
        request_arguments = request_section.get("arguments")
        if _has_meaningful_payload(request_arguments):
            retain_locations.add(request_location)

    response_locations: list[tuple[tuple[Any, ...], Any]] = []
    response_section = working.get("llm_response")
    if isinstance(response_section, Mapping):
        tool_calls = response_section.get("tool_calls")
        if isinstance(tool_calls, Sequence) and not isinstance(
            tool_calls, (str, bytes, bytearray)
        ):
            for index, call in enumerate(tool_calls):
                if not isinstance(call, Mapping):
                    continue
                call_arguments = call.get("arguments")
                if _has_meaningful_payload(call_arguments):
                    location = ("llm_response", "tool_calls", index, "arguments")
                    response_locations.append((location, call_arguments))
                    retain_locations.add(location)

    preferred_response_location: tuple[Any, ...] | None = None
    for location, arguments in response_locations:
        if _matches(arguments):
            preferred_response_location = location
            break
    if preferred_response_location is None and response_locations:
        preferred_response_location = response_locations[0][0]
    if preferred_response_location is not None:
        retain_locations.add(preferred_response_location)

    tool_result_location: tuple[Any, ...] | None = None
    tool_result = working.get("tool_result")
    if isinstance(tool_result, Mapping):
        tool_section = tool_result.get("tool")
        if isinstance(tool_section, Mapping):
            tool_arguments = tool_section.get("arguments")
            if _has_meaningful_payload(tool_arguments):
                tool_result_location = ("tool_result", "tool", "arguments")
                retain_locations.add(tool_result_location)

    # Drop duplicate arguments from the LLM request.
    if request_location not in retain_locations:
        request_section = working.get("llm_request")
        if isinstance(request_section, Mapping) and _matches(request_section.get("arguments")):
            trimmed = {k: v for k, v in request_section.items() if k != "arguments"}
            if trimmed:
                working["llm_request"] = trimmed
            else:
                working.pop("llm_request", None)

    # Drop duplicate arguments from the LLM response tool calls.
    if not (primary_location and primary_location[0] == "llm_response"):
        response_section = working.get("llm_response")
        if isinstance(response_section, Mapping):
            tool_calls = response_section.get("tool_calls")
            if isinstance(tool_calls, Sequence) and not isinstance(tool_calls, (str, bytes, bytearray)):
                calls_changed = False
                processed_calls: list[Any] = []
                for index, call in enumerate(tool_calls):
                    if not isinstance(call, Mapping):
                        processed_calls.append(call)
                        continue
                    call_mapping = dict(call)
                    call_arguments = call_mapping.get("arguments")
                    location = ("llm_response", "tool_calls", index, "arguments")
                    if location in retain_locations:
                        processed_calls.append(call_mapping)
                        continue
                    if _matches(call_arguments):
                        call_mapping.pop("arguments", None)
                        calls_changed = True
                    if call_mapping:
                        processed_calls.append(call_mapping)
                    else:
                        calls_changed = True
                if calls_changed:
                    updated_response = dict(response_section)
                    updated_response["tool_calls"] = processed_calls
                    if not processed_calls and len(updated_response) == 1:
                        working.pop("llm_response", None)
                    else:
                        working["llm_response"] = updated_response
    else:
        # Keep the canonical response call intact while trimming siblings.
        response_section = working.get("llm_response")
        if isinstance(response_section, Mapping):
            tool_calls = response_section.get("tool_calls")
            if isinstance(tool_calls, Sequence) and not isinstance(tool_calls, (str, bytes, bytearray)):
                calls_changed = False
                processed_calls: list[Any] = []
                target_index = primary_location[2] if len(primary_location) > 2 else None
                for index, call in enumerate(tool_calls):
                    if not isinstance(call, Mapping):
                        processed_calls.append(call)
                        continue
                    call_mapping = dict(call)
                    if index == target_index:
                        processed_calls.append(call_mapping)
                        continue
                    call_arguments = call_mapping.get("arguments")
                    location = ("llm_response", "tool_calls", index, "arguments")
                    if location in retain_locations:
                        processed_calls.append(call_mapping)
                        continue
                    if _matches(call_arguments):
                        call_mapping.pop("arguments", None)
                        calls_changed = True
                    if call_mapping:
                        processed_calls.append(call_mapping)
                    else:
                        calls_changed = True
                if calls_changed:
                    updated_response = dict(response_section)
                    updated_response["tool_calls"] = processed_calls
                    if not processed_calls and len(updated_response) == 1:
                        working.pop("llm_response", None)
                    else:
                        working["llm_response"] = updated_response

    return working


def _select_primary_tool_arguments(
    sections: Mapping[str, Any],
) -> tuple[tuple[Any, ...] | None, Any | None]:
    """Return the preferred arguments payload and its location."""

    response_section = sections.get("llm_response") if isinstance(sections, Mapping) else None
    if isinstance(response_section, Mapping):
        tool_calls = response_section.get("tool_calls")
        if isinstance(tool_calls, Sequence) and not isinstance(tool_calls, (str, bytes, bytearray)):
            for index, call in enumerate(tool_calls):
                if not isinstance(call, Mapping):
                    continue
                arguments = call.get("arguments")
                if _has_meaningful_payload(arguments):
                    return ("llm_response", "tool_calls", index, "arguments"), arguments

    request_section = sections.get("llm_request") if isinstance(sections, Mapping) else None
    if isinstance(request_section, Mapping):
        arguments = request_section.get("arguments")
        if _has_meaningful_payload(arguments):
            return ("llm_request", "arguments"), arguments

    tool_result = sections.get("tool_result") if isinstance(sections, Mapping) else None
    if isinstance(tool_result, Mapping):
        tool_section = tool_result.get("tool")
        if isinstance(tool_section, Mapping):
            arguments = tool_section.get("arguments")
            if _has_meaningful_payload(arguments):
                return ("tool_result", "tool", "arguments"), arguments

    return (None, None)


def _collect_unique_timestamps(
    payload: Mapping[str, Any]
) -> list[tuple[str, str]]:
    if not isinstance(payload, Mapping):
        return []

    seen: set[str] = set()
    collected: list[tuple[str, str]] = []
    for key in (
        "first_observed_at",
        "started_at",
        "observed_at",
        "last_observed_at",
        "completed_at",
    ):
        value = payload.get(key)
        if not isinstance(value, str):
            continue
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        collected.append((key, text))
    return collected


def _normalise_optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _has_meaningful_payload(value: Any) -> bool:
    """Return ``True`` when *value* contains data worth displaying."""

    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(_has_meaningful_payload(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_has_meaningful_payload(item) for item in value)
    return True


def _payload_information(value: Any) -> int:
    """Return a score approximating how much information *value* carries."""

    if value is None:
        return 0
    if isinstance(value, str):
        return 1 if value.strip() else 0
    if isinstance(value, Mapping):
        return sum(_payload_information(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return sum(_payload_information(item) for item in value)
    return 1


def _merge_prefer_rich_mapping(
    existing: Mapping[str, Any], candidate: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Merge two payloads, preferring keys with meaningful data."""

    if not isinstance(existing, Mapping):
        return candidate
    if not isinstance(candidate, Mapping):
        return existing

    merged: dict[str, Any] = dict(existing)
    changed = False

    for key, value in candidate.items():
        if key not in merged:
            merged[key] = value
            changed = True
            continue

        current = merged[key]
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged_value = _merge_prefer_rich_mapping(current, value)
            if merged_value is not current:
                merged[key] = merged_value
                changed = True
            continue

        if (
            isinstance(current, Sequence)
            and not isinstance(current, (str, bytes, bytearray))
            and isinstance(value, Sequence)
            and not isinstance(value, (str, bytes, bytearray))
        ):
            if not _has_meaningful_payload(current) and _has_meaningful_payload(value):
                merged[key] = value
                changed = True
            continue

        if not _has_meaningful_payload(current) and _has_meaningful_payload(value):
            merged[key] = value
            changed = True

    if changed:
        return merged

    if _payload_information(candidate) > _payload_information(existing):
        return candidate
    return existing


def _build_agent_events(
    turn_timestamp: TimestampInfo,
    streamed_responses: tuple[AgentResponse, ...],
    final_response: AgentResponse | None,
    tool_calls: tuple[ToolCallDetails, ...],
) -> tuple[AgentTimelineEvent, ...]:
    events: list[AgentTimelineEvent] = []
    order_index = 0

    def next_index() -> int:
        nonlocal order_index
        order_index += 1
        return order_index

    def normalise_timestamp(info: TimestampInfo | None) -> TimestampInfo:
        if info is None:
            return turn_timestamp
        if info.missing and not info.raw and not info.formatted and not info.occurred_at:
            return turn_timestamp
        return info

    def append_response(response: AgentResponse) -> None:
        events.append(
            AgentTimelineEvent(
                kind="response",
                timestamp=normalise_timestamp(response.timestamp),
                order_index=next_index(),
                response=response,
            )
        )

    def append_tool(detail: ToolCallDetails) -> None:
        timestamp = detail.timestamp
        if timestamp.missing and not timestamp.raw and not timestamp.formatted:
            timestamp = turn_timestamp
        events.append(
            AgentTimelineEvent(
                kind="tool",
                timestamp=timestamp,
                order_index=next_index(),
                tool_call=detail,
            )
        )

    tools_by_step: dict[int | None, list[ToolCallDetails]] = {}
    for detail in tool_calls:
        step_index = _extract_tool_step_index(detail)
        bucket = tools_by_step.setdefault(step_index, [])
        bucket.append(detail)

    def consume_tools(step_key: int | None) -> None:
        details = tools_by_step.pop(step_key, [])
        for detail in sorted(details, key=_tool_detail_sort_key):
            append_tool(detail)

    for response in streamed_responses:
        append_response(response)
        if response.step_index is not None:
            consume_tools(response.step_index)

    if final_response is not None:
        append_response(final_response)

    consume_tools(None)

    if tools_by_step:
        leftover: list[tuple[int | None, ToolCallDetails]] = []
        for step_key, details in tools_by_step.items():
            for detail in details:
                leftover.append((step_key, detail))
        leftover.sort(
            key=lambda item: (
                _tool_detail_sort_key(item[1]),
                -1 if item[0] is None else item[0],
            )
        )
        for _, detail in leftover:
            append_tool(detail)

    return tuple(events)


def _tool_detail_sort_key(detail: ToolCallDetails) -> tuple[int, _dt.datetime | None, int]:
    timestamp = detail.timestamp.occurred_at
    return (
        0 if timestamp is not None else 1,
        timestamp,
        detail.summary.index or 0,
    )


def _extract_tool_step_index(detail: ToolCallDetails) -> int | None:
    payloads: tuple[Any, ...] = (
        detail.raw_data,
        detail.summary.raw_payload,
    )
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        candidate = payload.get("step")
        if candidate is None:
            continue
        try:
            value = int(candidate)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return None


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


# ---------------------------------------------------------------------------
def _resolve_turn_timestamp(
    primary: TimestampInfo,
    *,
    final_response: AgentResponse | None,
    stream_timestamp: TimestampInfo | None,
    tool_timestamp: TimestampInfo | None,
    prompt_timestamp: TimestampInfo | None,
) -> TimestampInfo:
    if not primary.missing:
        return primary

    def pick(candidate: TimestampInfo | None) -> TimestampInfo | None:
        if candidate is None or candidate.missing:
            return None
        if candidate.raw:
            return candidate
        return None

    for option in (
        final_response.timestamp if final_response is not None else None,
        stream_timestamp,
        tool_timestamp,
        prompt_timestamp,
    ):
        chosen = pick(option)
        if chosen is not None:
            return chosen

    return primary


# ---------------------------------------------------------------------------
def _extract_request_context(entry: ChatEntry) -> tuple[dict[str, Any], ...]:
    messages = _extract_messages_from_mapping(
        getattr(entry, "raw_result", None),
        keys=("diagnostic", "llm_request", "messages"),
    )
    if not messages:
        messages = _extract_messages_from_mapping(
            getattr(entry, "diagnostic", None),
            keys=("llm_request_messages",),
        )
    if not isinstance(messages, Sequence) or isinstance(messages, (str, bytes, bytearray)):
        return ()
    collected: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, Mapping):
            collected.append(dict(message))
    return tuple(collected)


def _extract_messages_from_mapping(
    source: Any, *, keys: tuple[str, ...]
) -> Any:
    if not isinstance(source, Mapping):
        return ()
    current: Any = source
    for key in keys:
        if not isinstance(current, Mapping):
            return ()
        current = current.get(key)
    return current


# ---------------------------------------------------------------------------
def _iter_llm_request_sources(entry: ChatEntry) -> Iterable[Mapping[str, Any]]:
    sources: list[Mapping[str, Any]] = []
    diagnostic = entry.diagnostic
    if isinstance(diagnostic, Mapping):
        sources.append(diagnostic)
    raw_result = entry.raw_result
    if isinstance(raw_result, Mapping):
        sources.append(raw_result)
        diagnostic_raw = raw_result.get("diagnostic")
        if isinstance(diagnostic_raw, Mapping):
            sources.append(diagnostic_raw)
    return tuple(sources)


def _extract_llm_request_details(
    entry: ChatEntry,
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...] | None]:
    messages: tuple[dict[str, Any], ...] = ()
    sequence: tuple[dict[str, Any], ...] | None = None

    for source in _iter_llm_request_sources(entry):
        candidate_messages = _sanitize_message_list(
            source.get("llm_request_messages")
        )
        if candidate_messages:
            messages = candidate_messages
        candidate_sequence = _sanitize_request_sequence(
            source.get("llm_request_messages_sequence")
        )
        if candidate_sequence is None:
            candidate_sequence = _sanitize_request_sequence(
                source.get("llm_requests")
            )
        if candidate_sequence:
            sequence = candidate_sequence
            if not messages:
                last_messages = candidate_sequence[-1].get("messages")
                if isinstance(last_messages, Sequence):
                    fallback_messages = _sanitize_message_list(last_messages)
                    if fallback_messages:
                        messages = fallback_messages
        if messages and sequence is not None:
            break

    if not messages:
        messages = _fallback_llm_request_messages(entry)
        if messages and sequence is None:
            sequence = (
                {
                    "step": 1,
                    "messages": tuple(dict(message) for message in messages),
                },
            )

    if not messages:
        return (), None

    prepared_messages: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        safe_message = history_json_safe(message)
        if isinstance(safe_message, Mapping):
            prepared_messages.append(dict(safe_message))
    prepared_sequence: tuple[dict[str, Any], ...] | None = None
    if sequence is not None:
        sequence_items: list[dict[str, Any]] = []
        for item in sequence:
            if not isinstance(item, Mapping):
                continue
            safe_item = history_json_safe(item)
            if not isinstance(safe_item, Mapping):
                continue
            record = dict(safe_item)
            messages_payload = record.get("messages")
            sanitized_messages = _sanitize_message_list(messages_payload)
            if sanitized_messages:
                record["messages"] = tuple(dict(msg) for msg in sanitized_messages)
            elif "messages" in record:
                record["messages"] = ()
            sequence_items.append(record)
        prepared_sequence = tuple(sequence_items) if sequence_items else None

    return tuple(prepared_messages), prepared_sequence


def _sanitize_message_list(
    value: Any,
) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    sanitized: list[dict[str, Any]] = []
    for message in value:
        if isinstance(message, Mapping):
            safe = history_json_safe(message)
            if isinstance(safe, Mapping):
                sanitized.append(dict(safe))
    return tuple(sanitized)


def _sanitize_request_sequence(value: Any) -> tuple[dict[str, Any], ...] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return None
    sanitized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        safe_item = history_json_safe(item)
        if not isinstance(safe_item, Mapping):
            continue
        record = dict(safe_item)
        messages_payload = record.get("messages")
        sanitized_messages = _sanitize_message_list(messages_payload)
        if sanitized_messages:
            record["messages"] = tuple(dict(msg) for msg in sanitized_messages)
        elif "messages" in record:
            record["messages"] = ()
        sanitized.append(record)
    return tuple(sanitized) if sanitized else None


def _fallback_llm_request_messages(entry: ChatEntry) -> tuple[dict[str, Any], ...]:
    messages: list[dict[str, Any]] = []
    system_prompt = str(SYSTEM_PROMPT).strip()
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if entry.context_messages:
        for message in entry.context_messages:
            if isinstance(message, Mapping):
                safe_message = history_json_safe(message)
                if isinstance(safe_message, Mapping):
                    messages.append(dict(safe_message))
    prompt_text = (entry.prompt or "").strip()
    if prompt_text:
        messages.append({"role": "user", "content": prompt_text})
    return tuple(messages)


# ---------------------------------------------------------------------------
def _collect_llm_step_payloads(entry: ChatEntry) -> tuple[dict[str, Any], ...]:
    ordered: list[tuple[int, int | None, str, dict[str, Any]]] = []
    index_by_key: dict[str, int] = {}
    auto_counter = 0

    for source in _iter_llm_request_sources(entry):
        steps = source.get("llm_steps")
        if not isinstance(steps, Sequence) or isinstance(steps, (str, bytes, bytearray)):
            continue
        for step_payload in steps:
            safe_step = history_json_safe(step_payload)
            if not isinstance(safe_step, Mapping):
                continue
            record = dict(safe_step)
            step_value = record.get("step")
            numeric_index: int | None = None
            if isinstance(step_value, (int, float)):
                numeric_index = int(step_value)
                key = str(numeric_index)
            elif isinstance(step_value, str) and step_value.strip():
                key = step_value.strip()
                if key.isdigit():
                    try:
                        numeric_index = int(key)
                    except ValueError:
                        numeric_index = None
            else:
                auto_counter += 1
                key = f"auto-{auto_counter}"

            if key in index_by_key:
                position = index_by_key[key]
                order_index, _, existing_key, _ = ordered[position]
                ordered[position] = (order_index, numeric_index, existing_key, record)
            else:
                order_index = len(ordered)
                index_by_key[key] = order_index
                ordered.append((order_index, numeric_index, key, record))

    if not ordered:
        return ()

    ordered.sort(
        key=lambda item: (
            item[1] if item[1] is not None else item[0],
            item[0],
        )
    )
    return tuple(record for _, _, _, record in ordered)


def _normalise_message_text(value: str | None) -> str:
    if not value:
        return ""
    text = str(value)
    return " ".join(text.split())


# ---------------------------------------------------------------------------
def _extract_error_tool_calls(error_payload: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Return tool call payloads embedded into *error_payload*."""

    candidates: list[Mapping[str, Any]] = []

    def append(candidate: Any) -> None:
        if isinstance(candidate, Mapping):
            candidates.append(candidate)

    append(error_payload.get("tool_call"))

    for key in ("tool_calls", "llm_tool_calls"):
        option = error_payload.get(key)
        if isinstance(option, Mapping):
            append(option)
        elif isinstance(option, Sequence) and not isinstance(option, (str, bytes, bytearray)):
            for entry in option:
                append(entry)

    details = error_payload.get("details")
    if isinstance(details, Mapping):
        append(details.get("tool_call"))
        for key in ("tool_calls", "llm_tool_calls"):
            option = details.get(key)
            if isinstance(option, Mapping):
                append(option)
            elif isinstance(option, Sequence) and not isinstance(option, (str, bytes, bytearray)):
                for entry in option:
                    append(entry)

    return tuple(candidates)


# ---------------------------------------------------------------------------
def _normalise_raw_section(value: Any) -> Any:
    """Return a JSON-safe representation that can be merged structurally."""

    safe_value = history_json_safe(value)
    if isinstance(safe_value, Mapping):
        return {
            key: _normalise_raw_section(item)
            for key, item in safe_value.items()
        }
    if isinstance(safe_value, Sequence) and not isinstance(
        safe_value, (str, bytes, bytearray)
    ):
        return [_normalise_raw_section(item) for item in safe_value]
    return safe_value


def _decode_json_arguments(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value, False
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError):
            return value, False
        return decoded, True
    return value, False


def _decode_tool_call_arguments(call: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(call, Mapping):
        return call

    changed = False
    result: dict[str, Any] = dict(call)

    arguments_value, decoded = _decode_json_arguments(result.get("arguments"))
    if decoded:
        result["arguments"] = arguments_value
        changed = True

    function_section = result.get("function")
    if isinstance(function_section, Mapping):
        function_changed = False
        function_payload: dict[str, Any] = dict(function_section)

        function_arguments, function_arguments_decoded = _decode_json_arguments(
            function_payload.get("arguments")
        )
        if function_arguments_decoded:
            function_payload["arguments"] = function_arguments
            function_changed = True

        if (
            isinstance(function_arguments, Mapping)
            and (not isinstance(result.get("arguments"), Mapping) or not result["arguments"])
        ):
            result["arguments"] = function_arguments
            changed = True

        name_value = function_payload.get("name")
        if isinstance(name_value, str) and name_value and not result.get("name"):
            result["name"] = name_value
            changed = True

        if function_changed:
            result["function"] = function_payload
            changed = True

    return result if changed else call


def _decode_tool_call_sequence(value: Any) -> Any:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return value

    changed = False
    decoded_items: list[Any] = []
    for item in value:
        new_item = item
        if isinstance(item, Mapping):
            new_item = _decode_tool_calls_in_mapping(item)
        elif isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray)
        ):
            new_item = _decode_tool_call_sequence(item)
        decoded_items.append(new_item)
        if new_item is not item:
            changed = True
    return decoded_items if changed else value


def _decode_tool_calls_in_mapping(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        return payload

    changed = False
    base_payload = _decode_tool_call_arguments(payload)
    if base_payload is not payload:
        changed = True
    result: dict[str, Any] = {}

    for key, value in base_payload.items():
        new_value = value
        if key == "arguments":
            decoded_arguments, decoded = _decode_json_arguments(value)
            if decoded:
                new_value = decoded_arguments
        if key in {"tool_calls", "llm_tool_calls"}:
            new_value = _decode_tool_call_sequence(new_value)
        elif key in {"tool_call", "call"} and isinstance(new_value, Mapping):
            new_value = _decode_tool_calls_in_mapping(new_value)
        elif isinstance(new_value, Mapping):
            new_value = _decode_tool_calls_in_mapping(new_value)
        elif isinstance(new_value, Sequence) and not isinstance(
            new_value, (str, bytes, bytearray)
        ):
            new_value = _decode_tool_call_sequence(new_value)

        result[key] = new_value
        if new_value is not value:
            changed = True

    return result if changed else base_payload


def _decode_tool_calls_in_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _decode_tool_calls_in_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return _decode_tool_call_sequence(value)
    return value


def _collect_llm_tool_requests(entry: ChatEntry) -> dict[str, Mapping[str, Any]]:
    """Return per-tool snapshots of raw LLM data for *entry*."""

    snapshots: dict[str, dict[str, Any]] = {}

    def ensure(identifier: str) -> dict[str, Any]:
        snapshot = snapshots.get(identifier)
        if snapshot is None:
            snapshot = {}
            snapshots[identifier] = snapshot
        return snapshot

    def store_request(snapshot: dict[str, Any], payload: Mapping[str, Any] | None) -> None:
        if not isinstance(payload, Mapping):
            return
        normalised = _normalise_raw_section(_decode_tool_calls_in_mapping(payload))
        if not _has_meaningful_payload(normalised):
            return
        existing = snapshot.get("llm_request")
        if isinstance(existing, Mapping) and isinstance(normalised, Mapping):
            merged = _merge_prefer_rich_mapping(existing, normalised)
            if merged is not existing:
                snapshot["llm_request"] = merged
        elif existing is None or _payload_information(normalised) > _payload_information(existing):
            snapshot["llm_request"] = normalised

    def store_response(snapshot: dict[str, Any], payload: Any) -> None:
        normalised = _normalise_raw_section(_decode_tool_calls_in_value(payload))
        if not _has_meaningful_payload(normalised):
            return
        existing = snapshot.get("llm_response")
        if isinstance(existing, Mapping) and isinstance(normalised, Mapping):
            merged = _merge_prefer_rich_mapping(existing, normalised)
            if merged is not existing:
                snapshot["llm_response"] = merged
        elif existing is None or _payload_information(normalised) > _payload_information(existing):
            snapshot["llm_response"] = normalised

    def store_error(snapshot: dict[str, Any], payload: Mapping[str, Any] | None) -> None:
        if not isinstance(payload, Mapping):
            return
        normalised = _normalise_raw_section(_decode_tool_calls_in_mapping(payload))
        if not _has_meaningful_payload(normalised):
            return
        existing = snapshot.get("llm_error")
        if isinstance(existing, Mapping) and isinstance(normalised, Mapping):
            merged = _merge_prefer_rich_mapping(existing, normalised)
            if merged is not existing:
                snapshot["llm_error"] = merged
        elif existing is None or _payload_information(normalised) > _payload_information(existing):
            snapshot["llm_error"] = normalised

    def store_step(snapshot: dict[str, Any], step_value: Any) -> None:
        if step_value in (None, "") or "step" in snapshot:
            return
        snapshot["step"] = step_value

    def append_diagnostic(identifier: str, key: str, payload: Any) -> None:
        normalised = _normalise_raw_section(_decode_tool_calls_in_value(payload))
        if not _has_meaningful_payload(normalised):
            return
        snapshot = ensure(identifier)
        diagnostics = snapshot.setdefault("diagnostics", {})
        bucket = diagnostics.setdefault(key, [])
        bucket.append(normalised)

    for source in _iter_llm_request_sources(entry):
        steps = source.get("llm_steps")
        if isinstance(steps, Sequence):
            for step_index, step in enumerate(steps, start=1):
                if not isinstance(step, Mapping):
                    continue
                response_payload = _decode_tool_calls_in_value(step.get("response"))
                tool_calls = None
                if isinstance(response_payload, Mapping):
                    tool_calls = response_payload.get("tool_calls")
                if isinstance(tool_calls, Sequence) and not isinstance(
                    tool_calls, (str, bytes, bytearray)
                ):
                    for position, call in enumerate(tool_calls, start=1):
                        if not isinstance(call, Mapping):
                            continue
                        decoded_call = _decode_tool_calls_in_mapping(call)
                        identifier = (
                            _extract_tool_identifier(decoded_call)
                            or decoded_call.get("id")
                            or decoded_call.get("call_id")
                        )
                        if identifier is None:
                            identifier = f"{step_index}:{position}"
                        identifier_str = str(identifier)
                        snapshot = ensure(identifier_str)
                        store_request(snapshot, decoded_call)
                        store_response(snapshot, response_payload)
                        store_step(snapshot, step_index)
                elif response_payload is not None:
                    identifier = f"step:{step_index}"
                    snapshot = ensure(identifier)
                    store_response(snapshot, response_payload)
                    store_step(snapshot, step_index)

                error_payload = step.get("error")
                if not isinstance(error_payload, Mapping):
                    continue
                decoded_error = _decode_tool_calls_in_mapping(error_payload)
                step_value = decoded_error.get("step", step_index)
                request_candidate = decoded_error.get("request")
                response_candidate = decoded_error.get("response")
                error_calls = _extract_error_tool_calls(decoded_error)
                if error_calls:
                    for position, call in enumerate(error_calls, start=1):
                        decoded_call = _decode_tool_calls_in_mapping(call)
                        identifier = (
                            _extract_tool_identifier(decoded_call)
                            or decoded_call.get("id")
                            or decoded_call.get("call_id")
                        )
                        if identifier is None:
                            base = step_value if step_value not in (None, "") else step_index
                            identifier = f"{base}:{position}" if base not in (None, "") else f"error:{step_index}:{position}"
                        identifier_str = str(identifier)
                        snapshot = ensure(identifier_str)
                        store_request(snapshot, decoded_call)
                        store_response(snapshot, response_candidate)
                        store_error(snapshot, decoded_error)
                        store_step(snapshot, step_value)
                else:
                    identifier = step_value if step_value not in (None, "") else f"error:{step_index}"
                    snapshot = ensure(str(identifier))
                    store_response(snapshot, response_candidate)
                    store_error(snapshot, decoded_error)
                    store_request(snapshot, request_candidate if isinstance(request_candidate, Mapping) else None)
                    store_step(snapshot, step_value)

        decoded_source = _decode_tool_calls_in_mapping(source)
        tool_calls = decoded_source.get("tool_calls")
        if isinstance(tool_calls, Sequence) and not isinstance(
            tool_calls, (str, bytes, bytearray)
        ):
            for position, call in enumerate(tool_calls, start=1):
                if not isinstance(call, Mapping):
                    continue
                decoded_call = _decode_tool_calls_in_mapping(call)
                identifier = (
                    _extract_tool_identifier(decoded_call)
                    or decoded_call.get("id")
                    or decoded_call.get("call_id")
                    or f"tool:{position}"
                )
                diagnostic_entry: dict[str, Any] = {"call": decoded_call}
                context: dict[str, Any] = {}
                for key in (
                    "agent_status",
                    "status_updates",
                    "message_preview",
                    "response_snapshot",
                    "reasoning",
                ):
                    candidate = decoded_source.get(key)
                    normalised = _normalise_raw_section(candidate)
                    if _has_meaningful_payload(normalised):
                        context[key] = normalised
                if context:
                    diagnostic_entry["context"] = context
                append_diagnostic(str(identifier), "tool_calls", diagnostic_entry)

        planned_calls = decoded_source.get("llm_tool_calls")
        if isinstance(planned_calls, Sequence) and not isinstance(
            planned_calls, (str, bytes, bytearray)
        ):
            for position, call in enumerate(planned_calls, start=1):
                if not isinstance(call, Mapping):
                    continue
                decoded_call = _decode_tool_calls_in_mapping(call)
                identifier = (
                    _extract_tool_identifier(decoded_call)
                    or decoded_call.get("id")
                    or decoded_call.get("call_id")
                    or f"planned:{position}"
                )
                append_diagnostic(str(identifier), "llm_tool_calls", decoded_call)

        source_error = decoded_source.get("error")
        if isinstance(source_error, Mapping):
            identifier = (
                _extract_tool_identifier(source_error)
                or source_error.get("id")
                or source_error.get("call_id")
                or f"error:{len(snapshots) + 1}"
            )
            append_diagnostic(str(identifier), "errors", source_error)

    return snapshots


def _iter_tool_payloads(tool_source: Any) -> Iterable[Mapping[str, Any]]:
    payloads = normalise_tool_payloads(tool_source)
    if not payloads:
        return ()
    result: list[Mapping[str, Any]] = []
    for payload in payloads:
        if isinstance(payload, Mapping):
            result.append(payload)
    return tuple(result)


def _extract_tool_timestamp(payload: Mapping[str, Any]) -> str | None:
    for key in (
        "first_observed_at",
        "started_at",
        "observed_at",
        "last_observed_at",
        "completed_at",
    ):
        value = payload.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return None


def _extract_tool_identifier(payload: Mapping[str, Any]) -> str | None:
    for key in ("tool_call_id", "call_id", "id", "call_identifier"):
        value = payload.get(key)
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return None



# ---------------------------------------------------------------------------
def _sanitize_layout_hints(layout_hints: Any) -> dict[str, int]:
    if not isinstance(layout_hints, Mapping):
        return {}
    sanitized: dict[str, int] = {}
    for key, value in layout_hints.items():
        if not isinstance(key, str):
            continue
        width = _coerce_positive_int(value)
        if width is None:
            continue
        sanitized[key] = width
    return sanitized


def _can_regenerate_entry(
    entry_index: int,
    total_entries: int,
    entry: ChatEntry,
) -> bool:
    is_last_entry = entry_index == total_entries - 1
    has_response = bool(entry.response_at)
    return is_last_entry and has_response


def _coerce_positive_int(value: Any) -> int | None:
    try:
        width = int(value)
    except (TypeError, ValueError):
        return None
    if width <= 0:
        return None
    return width


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
