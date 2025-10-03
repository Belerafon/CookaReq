"""Turn-oriented view model for the agent chat transcript."""

from __future__ import annotations

import datetime as _dt
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any, Iterable, Literal, Mapping, Sequence

from ...llm.spec import SYSTEM_PROMPT
from ..chat_entry import ChatConversation, ChatEntry
from .history_utils import history_json_safe, sort_tool_payloads
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
    llm_request: Any | None = None


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


def build_conversation_timeline(
    conversation: ChatConversation,
) -> ConversationTimeline:
    """Return turn-oriented timeline for *conversation*."""

    entries: list[TranscriptEntry] = []
    total_entries = len(conversation.entries)

    for entry_index, entry in enumerate(conversation.entries):
        entry_id = f"{conversation.conversation_id}:{entry_index}"
        prompt = _build_prompt(entry)
        context_messages = _build_context_messages(entry)
        agent_turn = _build_agent_turn(entry_id, entry_index, entry)
        layout_hints = _sanitize_layout_hints(entry.layout_hints)
        can_regenerate = _can_regenerate_entry(entry_index, total_entries, entry)
        timeline_entry = TranscriptEntry(
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
        entries.append(timeline_entry)

    return ConversationTimeline(
        conversation_id=conversation.conversation_id,
        entries=tuple(entries),
    )


def build_transcript_segments(conversation: ChatConversation) -> TranscriptSegments:
    """Flatten *conversation* into ordered transcript segments."""

    timeline = build_conversation_timeline(conversation)
    segments: list[TranscriptSegment] = []
    entry_order: list[str] = []

    for timeline_entry in timeline.entries:
        entry_id = timeline_entry.entry_id
        entry_index = timeline_entry.entry_index
        entry_order.append(entry_id)
        layout_hints = dict(timeline_entry.layout_hints)

        if timeline_entry.prompt is not None or timeline_entry.context_messages:
            payload = PromptSegment(
                prompt=timeline_entry.prompt,
                context_messages=timeline_entry.context_messages,
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

        if (
            timeline_entry.agent_turn is not None
            or timeline_entry.can_regenerate
            or (timeline_entry.system_messages)
        ):
            payload = AgentSegment(
                turn=timeline_entry.agent_turn,
                layout_hints=dict(layout_hints),
                can_regenerate=timeline_entry.can_regenerate,
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

        for index, system_event in enumerate(timeline_entry.system_messages, start=1):
            segments.append(
                TranscriptSegment(
                    segment_id=f"{entry_id}:system:{index}",
                    entry_id=entry_id,
                    entry_index=entry_index,
                    kind="system",
                    payload=system_event,
                )
            )

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
    payloads = _iter_tool_payloads(entry.tool_results)
    if not payloads:
        return (), None

    requests = _collect_llm_tool_requests(entry)
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
        request_payload: Any | None = None
        if call_identifier is not None:
            request_payload = requests.get(call_identifier)
        if request_payload is None:
            request_payload = requests.get(str(tool_index))
        if request_payload is None:
            request_payload = _synthesise_tool_request(payload, summary)

        condensed_raw = _compose_tool_raw_data(request_payload)
        llm_request_snapshot = _extract_tool_llm_request(request_payload)
        if llm_request_snapshot is None and isinstance(condensed_raw, Mapping):
            candidate = condensed_raw.get("llm_request")
            if candidate is not None:
                llm_request_snapshot = candidate
        if condensed_raw is None:
            include_tool_result = False
            if isinstance(safe_payload, Mapping):
                diagnostic_keys = {
                    "agent_status",
                    "status_updates",
                    "error",
                    "result",
                    "tool_arguments",
                    "arguments",
                    "response",
                    "details",
                }
                include_tool_result = any(key in safe_payload for key in diagnostic_keys)
            if include_tool_result:
                condensed_raw = history_json_safe({"tool_result": safe_payload})
        elif isinstance(condensed_raw, Mapping) and isinstance(safe_payload, Mapping):
            if "tool_result" not in condensed_raw:
                enriched = dict(condensed_raw)
                enriched["tool_result"] = safe_payload
                condensed_raw = history_json_safe(enriched)

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
                llm_request=llm_request_snapshot,
            )
        )
    return tuple(tool_calls), latest_timestamp


def _compose_tool_raw_data(request_payload: Any) -> Any | None:
    """Return a condensed raw data payload for tool diagnostics."""

    if request_payload is None:
        return None

    safe_payload = history_json_safe(request_payload)

    if isinstance(safe_payload, Mapping):
        sections: dict[str, Any] = {}

        request_body = safe_payload.get("tool_call") or safe_payload.get("request")
        if request_body is None and "response" not in safe_payload:
            request_body = safe_payload
        if request_body is not None:
            sections["llm_request"] = history_json_safe(request_body)

        response_body = safe_payload.get("response")
        if response_body is not None:
            sections["llm_response"] = history_json_safe(response_body)

        step_value = safe_payload.get("step")
        if step_value is not None and step_value != "":
            sections["step"] = history_json_safe(step_value)

        return history_json_safe(sections) if sections else None

    if isinstance(safe_payload, Sequence) and not isinstance(
        safe_payload, (str, bytes, bytearray)
    ):
        return history_json_safe({"llm_request": list(safe_payload)})

    return history_json_safe({"llm_request": safe_payload})


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


def _extract_tool_llm_request(request_payload: Any) -> Any | None:
    """Return sanitised tool request payload extracted from *request_payload*."""

    if request_payload is None:
        return None

    if isinstance(request_payload, Mapping):
        if "tool_call" in request_payload:
            candidate = request_payload.get("tool_call")
        elif "request" in request_payload and "response" in request_payload:
            candidate = request_payload.get("request")
        elif "response" not in request_payload:
            candidate = request_payload
        else:
            candidate = None
        if candidate is None:
            return None
        return history_json_safe(candidate)

    if isinstance(request_payload, Sequence) and not isinstance(
        request_payload, (str, bytes, bytearray)
    ):
        return history_json_safe(list(request_payload))

    return history_json_safe(request_payload)


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
def _collect_llm_tool_requests(entry: ChatEntry) -> dict[str, Any]:
    """Gather raw LLM tool call payloads keyed by their identifiers."""

    requests: dict[str, Any] = {}

    def record(identifier: str, payload: Any) -> None:
        if not identifier:
            return
        safe_payload = history_json_safe(payload)
        if safe_payload is None:
            return
        if identifier in requests:
            existing = requests[identifier]
            if isinstance(existing, Mapping) and isinstance(safe_payload, Mapping):
                merged: dict[str, Any] = dict(existing)
                for key, value in safe_payload.items():
                    if key == "tool_call" and isinstance(value, Mapping):
                        existing_tool = (
                            merged.get("tool_call")
                            if isinstance(merged.get("tool_call"), Mapping)
                            else None
                        )
                        if isinstance(existing_tool, Mapping):
                            merged_tool = dict(existing_tool)
                            for tool_key, tool_value in value.items():
                                merged_tool[tool_key] = tool_value
                        else:
                            merged_tool = dict(value)
                        merged["tool_call"] = merged_tool
                    else:
                        merged[key] = value
                sanitized = history_json_safe(merged)
                requests[identifier] = sanitized if sanitized is not None else merged
                return
        requests[identifier] = safe_payload

    def scan_tool_calls(
        tool_calls: Any,
        *,
        response_payload: Mapping[str, Any] | None = None,
        step_index: int | None = None,
    ) -> None:
        if not isinstance(tool_calls, Sequence) or isinstance(
            tool_calls, (str, bytes, bytearray)
        ):
            return
        for position, call in enumerate(tool_calls, start=1):
            if not isinstance(call, Mapping):
                continue
            identifier = _extract_tool_identifier(call)
            if identifier is None:
                identifier = call.get("id") or str(position)
            payload: dict[str, Any] = dict(call)
            if response_payload is not None:
                payload = {
                    "tool_call": history_json_safe(call),
                    "response": history_json_safe(response_payload),
                }
                if step_index is not None:
                    payload["step"] = step_index
            record(identifier, payload)

    for source in _iter_llm_request_sources(entry):
        steps = source.get("llm_steps")
        if isinstance(steps, Sequence):
            for step_index, step in enumerate(steps, start=1):
                if not isinstance(step, Mapping):
                    continue
                response_payload = step.get("response")
                if isinstance(response_payload, Mapping):
                    scan_tool_calls(
                        response_payload.get("tool_calls"),
                        response_payload=response_payload,
                        step_index=step_index,
                    )
                    if not response_payload.get("tool_calls"):
                        record(
                            str(len(requests) + 1),
                            {
                                "response": history_json_safe(response_payload),
                                "step": step_index,
                            },
                        )
        scan_tool_calls(source.get("tool_calls"), response_payload=source)
        planned_calls = source.get("llm_tool_calls")
        scan_tool_calls(planned_calls, response_payload=source)

    return requests


def _iter_tool_payloads(tool_results: Sequence[Any] | None) -> Iterable[Mapping[str, Any]]:
    if not tool_results:
        return ()
    ordered = sort_tool_payloads(tool_results)
    result: list[Mapping[str, Any]] = []
    for payload in ordered:
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


def _synthesise_tool_request(
    payload: Mapping[str, Any], summary: ToolCallSummary | None
) -> Any | None:
    """Reconstruct an approximate LLM request when none was recorded."""

    if not isinstance(payload, Mapping):
        return None

    arguments_source: Any = None
    for key in ("tool_arguments", "arguments", "args"):
        candidate = payload.get(key)
        if isinstance(candidate, Mapping):
            arguments_source = candidate
            break
    if not isinstance(arguments_source, Mapping):
        return None

    safe_arguments = history_json_safe(arguments_source)
    if not isinstance(safe_arguments, Mapping):
        return None

    request: dict[str, Any] = {
        "tool_call": {
            "name": summary.tool_name if summary else "",
            "arguments": dict(safe_arguments),
        }
    }

    if not request["tool_call"]["name"]:
        for key in ("tool_name", "name", "tool"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                request["tool_call"]["name"] = value.strip()
                break

    step_value = payload.get("step")
    if step_value is not None:
        request["step"] = step_value

    return history_json_safe(request)


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
    "build_conversation_timeline",
    "build_transcript_segments",
]
