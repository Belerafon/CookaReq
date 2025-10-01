"""Turn-oriented view model for the agent chat transcript."""

from __future__ import annotations

import datetime as _dt
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Sequence

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
class LlmRequestSnapshot:
    """Recorded messages that were sent to the language model."""

    messages: tuple[dict[str, Any], ...]
    sequence: tuple[dict[str, Any], ...] | None


@dataclass(slots=True)
class ToolCallDetails:
    """Diagnostic information about an MCP tool invocation."""

    summary: ToolCallSummary
    call_identifier: str | None
    raw_payload: Any
    llm_request: Any | None


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
    streamed_responses = _build_streamed_responses(entry, final_response)
    reasoning_segments = _sanitize_reasoning_segments(entry.reasoning)
    llm_request = _build_llm_request_snapshot(entry)
    tool_calls = _build_tool_calls(entry_id, entry_index, entry)
    raw_payload = history_json_safe(entry.raw_result)

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
) -> tuple[AgentResponse, ...]:
    payloads = _collect_llm_step_payloads(entry)
    if not payloads:
        return ()

    final_text = _normalise_message_text(
        final_response.display_text if final_response else None
    )

    responses: list[AgentResponse] = []
    fallback_index = 1
    for payload in payloads:
        response = _build_stream_step_response(payload, fallback_index)
        if response is None:
            continue
        fallback_index = (response.step_index or fallback_index) + 1
        if final_text and _normalise_message_text(response.display_text) == final_text:
            continue
        responses.append(response)
    return tuple(responses)


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
) -> tuple[ToolCallDetails, ...]:
    payloads = _iter_tool_payloads(entry.tool_results)
    if not payloads:
        return ()

    requests = _collect_llm_tool_requests(entry)
    tool_calls: list[ToolCallDetails] = []
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

        tool_calls.append(
            ToolCallDetails(
                summary=summary,
                call_identifier=call_identifier,
                raw_payload=safe_payload,
                llm_request=request_payload,
            )
        )
    return tuple(tool_calls)


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
        if identifier in requests:
            existing = requests[identifier]
            if isinstance(existing, Mapping) and isinstance(payload, Mapping):
                if "response" in existing and "response" not in payload:
                    return
        safe_payload = history_json_safe(payload)
        if safe_payload is None:
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
    "LlmRequestSnapshot",
    "ToolCallDetails",
    "AgentTurn",
    "SystemMessage",
    "TranscriptEntry",
    "ConversationTimeline",
    "build_conversation_timeline",
]
