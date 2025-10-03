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
class ToolCallRawRecord:
    """Raw diagnostic sections captured for a tool call."""

    exchange: Mapping[str, Any] | None = None
    diagnostics: Mapping[str, Any] | None = None


@dataclass(slots=True)
class ToolCallDetails:
    """Diagnostic information about an MCP tool invocation."""

    summary: ToolCallSummary
    call_identifier: str | None
    raw_data: Any | None
    timestamp: TimestampInfo
    llm_request: Any | None = None
    llm_exchange: Mapping[str, Any] | None = None
    diagnostics: Mapping[str, Any] | None = None


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
        raw_record: ToolCallRawRecord | None = None
        if call_identifier is not None:
            raw_record = raw_records.get(call_identifier)
        if raw_record is None:
            raw_record = raw_records.get(str(tool_index))
        if raw_record is None:
            raw_record = _synthesise_tool_request(payload, summary)

        condensed_raw = _compose_tool_raw_data(raw_record)
        llm_exchange_payload: Mapping[str, Any] | None = None
        diagnostics_payload: Mapping[str, Any] | None = None
        llm_request_snapshot: Any | None = None

        if isinstance(condensed_raw, Mapping):
            exchange_candidate = condensed_raw.get("llm_exchange")
            if isinstance(exchange_candidate, Mapping):
                llm_exchange_payload = exchange_candidate
                request_candidate = exchange_candidate.get("llm_request")
                if request_candidate is not None:
                    llm_request_snapshot = request_candidate
            diagnostics_candidate = condensed_raw.get("diagnostics")
            if isinstance(diagnostics_candidate, Mapping):
                diagnostics_payload = diagnostics_candidate

        if llm_request_snapshot is None:
            llm_request_snapshot = _extract_tool_llm_request(raw_record)

        raw_sections: dict[str, Any] = {}
        if isinstance(condensed_raw, Mapping):
            raw_sections.update(condensed_raw)

        tool_result_section: Mapping[str, Any] | None = None
        if isinstance(safe_payload, Mapping):
            tool_result_section = _compose_tool_result_section(safe_payload)
        if tool_result_section is not None:
            raw_sections["tool_result"] = tool_result_section

        condensed_raw = history_json_safe(raw_sections) if raw_sections else None

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
                llm_exchange=llm_exchange_payload,
                diagnostics=diagnostics_payload,
            )
        )
    return tuple(tool_calls), latest_timestamp


def _compose_tool_raw_data(request_payload: Any) -> Any | None:
    """Return a condensed raw data payload for tool diagnostics."""

    if request_payload is None:
        return None

    exchange_section: Mapping[str, Any] | None = None
    diagnostics_section: Mapping[str, Any] | None = None

    if isinstance(request_payload, ToolCallRawRecord):
        if request_payload.exchange is not None:
            exchange_payload = history_json_safe(request_payload.exchange)
            if isinstance(exchange_payload, Mapping):
                exchange_section = _build_exchange_section(exchange_payload)
        if request_payload.diagnostics is not None:
            diagnostics_payload = history_json_safe(request_payload.diagnostics)
            if _has_meaningful_payload(diagnostics_payload):
                diagnostics_section = diagnostics_payload
    else:
        safe_payload = history_json_safe(request_payload)
        exchange_section = _build_exchange_section_from_safe_payload(safe_payload)

    sections: dict[str, Any] = {}
    if exchange_section:
        sections["llm_exchange"] = exchange_section
    if diagnostics_section:
        sections["diagnostics"] = diagnostics_section

    return history_json_safe(sections) if sections else None


def _build_exchange_section(
    exchange_payload: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    if not isinstance(exchange_payload, Mapping):
        return None

    section: dict[str, Any] = {}
    for key in ("llm_request", "llm_response", "llm_error", "step"):
        if key not in exchange_payload:
            continue
        candidate = history_json_safe(exchange_payload.get(key))
        if _has_meaningful_payload(candidate):
            section[key] = candidate

    additional_payload = history_json_safe(exchange_payload.get("additional"))
    if _has_meaningful_payload(additional_payload):
        section["additional"] = additional_payload

    return section or None


def _build_exchange_section_from_safe_payload(
    safe_payload: Any,
) -> Mapping[str, Any] | None:
    if isinstance(safe_payload, Mapping):
        section: dict[str, Any] = {}

        request_body = safe_payload.get("tool_call") or safe_payload.get("request")
        if request_body is None and "response" not in safe_payload:
            request_body = safe_payload
        if request_body is not None:
            request_section = history_json_safe(request_body)
            if _has_meaningful_payload(request_section):
                section["llm_request"] = request_section

        response_body = safe_payload.get("response")
        if response_body is not None:
            response_section = history_json_safe(response_body)
            if _has_meaningful_payload(response_section):
                section["llm_response"] = response_section

        error_body = safe_payload.get("error")
        if error_body is not None:
            error_section = history_json_safe(error_body)
            if _has_meaningful_payload(error_section):
                section["llm_error"] = error_section

        step_value = safe_payload.get("step")
        if step_value is not None and step_value != "":
            step_section = history_json_safe(step_value)
            if _has_meaningful_payload(step_section):
                section["step"] = step_section

        extras: dict[str, Any] = {}
        for key, value in safe_payload.items():
            if key in {"tool_call", "request", "response", "error", "step"}:
                continue
            sanitized = history_json_safe(value)
            if _has_meaningful_payload(sanitized):
                extras[key] = sanitized
        if extras:
            section["additional"] = history_json_safe(extras)

        return section or None

    if isinstance(safe_payload, Sequence) and not isinstance(
        safe_payload, (str, bytes, bytearray)
    ):
        request_section = history_json_safe(list(safe_payload))
        if _has_meaningful_payload(request_section):
            return {"llm_request": request_section}
        return None

    if _has_meaningful_payload(safe_payload):
        return {"llm_request": safe_payload}

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

    return history_json_safe(sections) if sections else None


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

    if isinstance(request_payload, ToolCallRawRecord):
        return _extract_tool_llm_request(request_payload.exchange)

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
        detail.llm_exchange,
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


def _merge_structured_values(existing: Any, update: Any) -> Any:
    """Merge *update* into *existing* preserving nested structures."""

    if existing is None:
        return update
    if isinstance(existing, dict) and isinstance(update, dict):
        merged = dict(existing)
        for key, value in update.items():
            merged[key] = _merge_structured_values(merged.get(key), value)
        return merged
    if isinstance(existing, list) and isinstance(update, list):
        merged = list(existing)
        for item in update:
            if item not in merged:
                merged.append(item)
        return merged
    return update


def _merge_structured_mappings(
    existing: Mapping[str, Any] | None, update: Mapping[str, Any]
) -> dict[str, Any]:
    base: dict[str, Any] = dict(existing) if isinstance(existing, Mapping) else {}
    for key, value in update.items():
        base[key] = _merge_structured_values(base.get(key), value)
    return base


def _build_diagnostic_context(payload: Any) -> Mapping[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    context_keys = (
        "agent_status",
        "status_updates",
        "message_preview",
        "response_snapshot",
        "reasoning",
    )
    context: dict[str, Any] = {}
    for key in context_keys:
        if key not in payload:
            continue
        normalised = _normalise_raw_section(payload.get(key))
        if _has_meaningful_payload(normalised):
            context[key] = normalised
    return context or None


def _collect_llm_tool_requests(entry: ChatEntry) -> dict[str, ToolCallRawRecord]:
    """Gather raw LLM tool call payloads keyed by their identifiers."""

    records: dict[str, ToolCallRawRecord] = {}

    def ensure_record(identifier: str) -> ToolCallRawRecord:
        record = records.get(identifier)
        if record is None:
            record = ToolCallRawRecord()
            records[identifier] = record
        return record

    def merge_exchange(identifier: str, sections: Mapping[str, Any]) -> None:
        sanitized: dict[str, Any] = {}
        for key, value in sections.items():
            normalised = _normalise_raw_section(value)
            if _has_meaningful_payload(normalised):
                sanitized[key] = normalised
        if not sanitized:
            return
        record = ensure_record(identifier)
        record.exchange = _merge_structured_mappings(record.exchange, sanitized)

    def add_diagnostics(identifier: str, section: str, payload: Any) -> None:
        normalised = _normalise_raw_section(payload)
        if not _has_meaningful_payload(normalised):
            return
        record = ensure_record(identifier)
        record.diagnostics = _merge_structured_mappings(
            record.diagnostics, {section: normalised}
        )

    def record_error_payload(
        error_payload: Mapping[str, Any], *, step_index: int | None
    ) -> bool:
        tool_calls = _extract_error_tool_calls(error_payload)
        recorded = False

        step_value: Any | None = step_index
        if step_value is None:
            candidate_step = error_payload.get("step")
            if candidate_step not in (None, ""):
                step_value = candidate_step

        response_candidate = _normalise_raw_section(error_payload.get("response"))
        request_candidate = _normalise_raw_section(error_payload.get("request"))

        if tool_calls:
            for position, call in enumerate(tool_calls, start=1):
                identifier = (
                    _extract_tool_identifier(call)
                    or call.get("id")
                    or call.get("call_id")
                )
                if identifier is None:
                    base = str(step_value) if step_value is not None else "error"
                    identifier = f"{base}:{position}"
                call_payload = _normalise_raw_section(call)
                error_section = _normalise_raw_section(error_payload)
                identifier_str = str(identifier)
                if step_index is not None:
                    sections: dict[str, Any] = {}
                    if request_candidate is not None:
                        sections["llm_request"] = request_candidate
                    elif call_payload is not None:
                        sections["llm_request"] = call_payload
                    if response_candidate is not None:
                        sections["llm_response"] = response_candidate
                    if error_section is not None:
                        sections["llm_error"] = error_section
                    if step_value is not None:
                        sections["step"] = step_value
                    merge_exchange(identifier_str, sections)
                    recorded = True
                else:
                    diagnostic_entry: dict[str, Any] = {}
                    if call_payload is not None:
                        diagnostic_entry["call"] = call_payload
                    if request_candidate is not None:
                        diagnostic_entry["request"] = request_candidate
                    if response_candidate is not None:
                        diagnostic_entry["response"] = response_candidate
                    if error_section is not None:
                        diagnostic_entry["error"] = error_section
                    if diagnostic_entry:
                        add_diagnostics(identifier_str, "errors", diagnostic_entry)
        else:
            if step_index is not None:
                identifier = str(step_value) if step_value is not None else str(step_index)
                sections: dict[str, Any] = {
                    "llm_error": _normalise_raw_section(error_payload)
                }
                if request_candidate is not None:
                    sections["llm_request"] = request_candidate
                if response_candidate is not None:
                    sections["llm_response"] = response_candidate
                if step_value is not None:
                    sections["step"] = step_value
                merge_exchange(identifier, sections)
                recorded = True
            else:
                diagnostic_entry: dict[str, Any] = {
                    "error": _normalise_raw_section(error_payload)
                }
                if request_candidate is not None:
                    diagnostic_entry["request"] = request_candidate
                if response_candidate is not None:
                    diagnostic_entry["response"] = response_candidate
                add_diagnostics(
                    f"error:{len(records) + 1}", "errors", diagnostic_entry
                )

        return recorded

    def scan_tool_calls(
        tool_calls: Any,
        *,
        response_payload: Mapping[str, Any] | None,
        step_index: int | None,
        origin: str,
    ) -> None:
        if not isinstance(tool_calls, Sequence) or isinstance(
            tool_calls, (str, bytes, bytearray)
        ):
            return
        for position, call in enumerate(tool_calls, start=1):
            if not isinstance(call, Mapping):
                continue
            identifier = (
                _extract_tool_identifier(call)
                or call.get("id")
                or call.get("call_id")
            )
            if identifier is None:
                base = str(step_index) if step_index is not None else str(position)
                identifier = (
                    f"{base}:{position}" if step_index is not None else str(position)
                )
            identifier = str(identifier)
            call_payload = _normalise_raw_section(call)
            if origin == "step":
                sections: dict[str, Any] = {}
                if call_payload is not None:
                    sections["llm_request"] = call_payload
                if response_payload is not None:
                    sections["llm_response"] = _normalise_raw_section(
                        response_payload
                    )
                if step_index is not None:
                    sections["step"] = step_index
                merge_exchange(identifier, sections)
            else:
                diagnostic_entry: dict[str, Any] = {}
                if call_payload is not None:
                    diagnostic_entry["call"] = call_payload
                context = _build_diagnostic_context(response_payload)
                if context:
                    diagnostic_entry["context"] = context
                if diagnostic_entry:
                    add_diagnostics(identifier, origin, diagnostic_entry)

    for source in _iter_llm_request_sources(entry):
        recorded_error_for_source = False
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
                        origin="step",
                    )
                    if not response_payload.get("tool_calls"):
                        fallback_id = str(len(records) + 1)
                        sections: dict[str, Any] = {
                            "llm_response": response_payload,
                            "step": step_index,
                        }
                        merge_exchange(fallback_id, sections)
                error_payload = step.get("error")
                if isinstance(error_payload, Mapping):
                    if record_error_payload(error_payload, step_index=step_index):
                        recorded_error_for_source = True
        scan_tool_calls(
            source.get("tool_calls"),
            response_payload=source,
            step_index=None,
            origin="tool_calls",
        )
        planned_calls = source.get("llm_tool_calls")
        scan_tool_calls(
            planned_calls,
            response_payload=source,
            step_index=None,
            origin="llm_tool_calls",
        )
        if not recorded_error_for_source:
            source_error = source.get("error")
            if isinstance(source_error, Mapping):
                record_error_payload(source_error, step_index=None)

    return records


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
) -> ToolCallRawRecord | None:
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

    normalised_request = _normalise_raw_section(request)
    if not isinstance(normalised_request, Mapping):
        return None

    exchange: dict[str, Any] = {}
    call_section = normalised_request.get("tool_call")
    if isinstance(call_section, Mapping) and _has_meaningful_payload(call_section):
        exchange["llm_request"] = call_section
    step_section = normalised_request.get("step")
    if _has_meaningful_payload(step_section):
        exchange["step"] = step_section

    extras: dict[str, Any] = {}
    for key, value in normalised_request.items():
        if key in {"tool_call", "step"}:
            continue
        if _has_meaningful_payload(value):
            extras[key] = value
    if extras:
        exchange["additional"] = extras

    if not exchange:
        return None

    return ToolCallRawRecord(exchange=exchange)


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
