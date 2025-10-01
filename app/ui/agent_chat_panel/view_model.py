"""Event-oriented view model for the agent chat transcript."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass, field, replace
from enum import Enum
import itertools
from typing import Any, Iterable, Mapping, Sequence
import datetime as _dt

from ...llm.spec import SYSTEM_PROMPT

from ..chat_entry import ChatConversation, ChatEntry
from .history_utils import history_json_safe, sort_tool_payloads
from .time_formatting import format_entry_timestamp, parse_iso_timestamp
from .tool_summaries import ToolCallSummary, summarize_tool_payload


class ChatEventKind(str, Enum):
    """Enumerate supported transcript event categories."""

    PROMPT = "prompt"
    CONTEXT = "context"
    REASONING = "reasoning"
    RESPONSE = "response"
    LLM_REQUEST = "llm_request"
    TOOL_CALL = "tool_call"
    RAW_PAYLOAD = "raw_payload"
    SYSTEM_MESSAGE = "system_message"


@dataclass(slots=True)
class ChatEvent:
    """Base class for all transcript events."""

    event_id: str
    entry_id: str
    entry_index: int
    sequence_index: int
    kind: ChatEventKind
    occurred_at: _dt.datetime | None
    timestamp: str | None


def _choose_timestamp(*candidates: str | None) -> str | None:
    """Return the first usable timestamp text from *candidates*."""

    for value in candidates:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return None


@dataclass(slots=True)
class PromptEvent(ChatEvent):
    """User prompt issued to the agent."""

    text: str
    formatted_timestamp: str


@dataclass(slots=True)
class ContextEvent(ChatEvent):
    """Contextual messages the agent received."""

    messages: tuple[dict[str, Any], ...]


@dataclass(slots=True)
class ReasoningEvent(ChatEvent):
    """Reasoning segments returned by the agent."""

    segments: tuple[dict[str, Any], ...]


@dataclass(slots=True)
class ResponseEvent(ChatEvent):
    """Visible response emitted by the agent."""

    text: str
    display_text: str
    formatted_timestamp: str
    regenerated: bool
    step_index: int | None = None
    is_final: bool = False


@dataclass(slots=True)
class LlmRequestEvent(ChatEvent):
    """Snapshot of LLM request messages for the entry."""

    messages: tuple[dict[str, Any], ...]
    sequence: tuple[dict[str, Any], ...] | None


@dataclass(slots=True)
class ToolCallEvent(ChatEvent):
    """Diagnostic information about a single tool call."""

    summary: ToolCallSummary
    call_identifier: str | None
    raw_payload: Any
    llm_request: Any | None


@dataclass(slots=True)
class RawPayloadEvent(ChatEvent):
    """Complete raw LLM payload for the entry."""

    payload: Any


@dataclass(slots=True)
class SystemMessageEvent(ChatEvent):
    """System-level diagnostic entry."""

    message: str
    details: Any | None = None


@dataclass(slots=True)
class EntryTimeline:
    """Ordered collection of events derived from a single chat entry."""

    entry_id: str
    entry_index: int
    entry: ChatEntry
    prompt: PromptEvent
    response: ResponseEvent | None
    intermediate_responses: tuple[ResponseEvent, ...]
    context: ContextEvent | None
    reasoning: ReasoningEvent | None
    llm_request: LlmRequestEvent | None
    tool_calls: tuple[ToolCallEvent, ...]
    raw_payload: RawPayloadEvent | None
    system_messages: tuple[SystemMessageEvent, ...]
    layout_hints: dict[str, int]
    can_regenerate: bool
    _events: tuple[ChatEvent, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        ordered: list[ChatEvent] = [self.prompt]
        if self.context is not None:
            ordered.append(self.context)
        if self.llm_request is not None:
            ordered.append(self.llm_request)
        if self.reasoning is not None:
            ordered.append(self.reasoning)
        ordered.extend(self.intermediate_responses)
        if self.response is not None:
            ordered.append(self.response)
        ordered.extend(self.tool_calls)
        if self.raw_payload is not None:
            ordered.append(self.raw_payload)
        ordered.extend(self.system_messages)
        self._events = tuple(ordered)

    @property
    def events(self) -> tuple[ChatEvent, ...]:
        """Return all events for the entry preserving chronological order."""

        return self._events


@dataclass(slots=True)
class ConversationTimeline:
    """Timeline representation of a conversation ready for rendering."""

    conversation_id: str
    entries: tuple[EntryTimeline, ...]
    events: tuple[ChatEvent, ...] = field(init=False)

    def __post_init__(self) -> None:
        self.events = tuple(
            event for entry in self.entries for event in entry.events
        )


def build_conversation_timeline(
    conversation: ChatConversation,
) -> ConversationTimeline:
    """Return structured timeline for *conversation*."""

    entries: list[EntryTimeline] = []
    sequence_counter = itertools.count()
    total_entries = len(conversation.entries)
    conversation_created_at = conversation.created_at
    conversation_updated_at = conversation.updated_at

    for entry_index, entry in enumerate(conversation.entries):
        entry_id = f"{conversation.conversation_id}:{entry_index}"
        prompt_event = _build_prompt_event(
            entry_id,
            entry_index,
            next(sequence_counter),
            entry,
            fallback_timestamp=_choose_timestamp(
                entry.prompt_at,
                entry.response_at,
                conversation_created_at,
                conversation_updated_at,
            ),
        )
        context_event = _build_context_event(
            entry_id,
            entry_index,
            next(sequence_counter),
            entry,
            fallback_timestamp=_choose_timestamp(
                entry.prompt_at,
                entry.response_at,
                conversation_created_at,
                conversation_updated_at,
            ),
        )
        reasoning_event = _build_reasoning_event(
            entry_id,
            entry_index,
            next(sequence_counter),
            entry,
            fallback_timestamp=_choose_timestamp(
                entry.response_at,
                entry.prompt_at,
                conversation_updated_at,
                conversation_created_at,
            ),
        )
        llm_request_event = _build_llm_request_event(
            entry_id,
            entry_index,
            next(sequence_counter),
            entry,
            fallback_timestamp=_choose_timestamp(
                entry.response_at,
                entry.prompt_at,
                conversation_updated_at,
                conversation_created_at,
            ),
        )
        step_events = _build_step_response_events(
            entry_id,
            entry_index,
            sequence_counter,
            entry,
            final_response_text=entry.display_response or entry.response,
            fallback_timestamp=_choose_timestamp(
                entry.response_at,
                entry.prompt_at,
                conversation_updated_at,
                conversation_created_at,
            ),
        )
        response_event = _build_response_event(
            entry_id,
            entry_index,
            next(sequence_counter),
            entry,
            fallback_timestamp=_choose_timestamp(
                entry.response_at,
                entry.prompt_at,
                conversation_updated_at,
                conversation_created_at,
            ),
        )
        tool_request_map = _collect_llm_tool_requests(entry)
        tool_call_events = tuple(
            _build_tool_call_event(
                entry_id,
                entry_index,
                next(sequence_counter),
                tool_index,
                payload,
                tool_request_map,
                fallback_timestamp=_choose_timestamp(
                    _extract_tool_timestamp(payload),
                    entry.response_at,
                    entry.prompt_at,
                    conversation_updated_at,
                    conversation_created_at,
                ),
            )
            for tool_index, payload in enumerate(
                _iter_tool_payloads(entry.tool_results), start=1
            )
        )
        raw_payload_event = _build_raw_payload_event(
            entry_id,
            entry_index,
            next(sequence_counter),
            entry,
            fallback_timestamp=_choose_timestamp(
                entry.response_at,
                entry.prompt_at,
                conversation_updated_at,
                conversation_created_at,
            ),
        )
        system_messages: tuple[SystemMessageEvent, ...] = ()
        layout_hints = _sanitize_layout_hints(entry.layout_hints)
        can_regenerate = _can_regenerate_entry(entry_index, total_entries, entry)
        timeline_entry = EntryTimeline(
            entry_id=entry_id,
            entry_index=entry_index,
            entry=entry,
            prompt=prompt_event,
            response=response_event,
            intermediate_responses=step_events,
            context=context_event,
            reasoning=reasoning_event,
            llm_request=llm_request_event,
            tool_calls=tool_call_events,
            raw_payload=raw_payload_event,
            system_messages=system_messages,
            layout_hints=layout_hints,
            can_regenerate=can_regenerate,
        )
        entries.append(timeline_entry)

    return ConversationTimeline(
        conversation_id=conversation.conversation_id,
        entries=tuple(entries),
    )


# ---------------------------------------------------------------------------
def _build_prompt_event(
    entry_id: str,
    entry_index: int,
    sequence_index: int,
    entry: ChatEntry,
    *,
    fallback_timestamp: str | None,
) -> PromptEvent:
    timestamp_source = entry.prompt_at or entry.response_at or fallback_timestamp
    occurred_at = parse_iso_timestamp(timestamp_source)
    formatted_timestamp = format_entry_timestamp(timestamp_source)
    timestamp = timestamp_source
    return PromptEvent(
        event_id=f"{entry_id}:prompt",
        entry_id=entry_id,
        entry_index=entry_index,
        sequence_index=sequence_index,
        kind=ChatEventKind.PROMPT,
        occurred_at=occurred_at,
        timestamp=timestamp,
        text=entry.prompt,
        formatted_timestamp=formatted_timestamp,
    )


# ---------------------------------------------------------------------------
def _build_context_event(
    entry_id: str,
    entry_index: int,
    sequence_index: int,
    entry: ChatEntry,
    *,
    fallback_timestamp: str | None,
) -> ContextEvent | None:
    messages_raw = entry.context_messages or _extract_request_context(entry)
    if not messages_raw:
        return None
    messages: list[dict[str, Any]] = []
    for message in messages_raw:
        if isinstance(message, Mapping):
            messages.append(dict(message))
    if not messages:
        return None
    timestamp = entry.prompt_at or entry.response_at or fallback_timestamp
    occurred_at = parse_iso_timestamp(timestamp)
    return ContextEvent(
        event_id=f"{entry_id}:context",
        entry_id=entry_id,
        entry_index=entry_index,
        sequence_index=sequence_index,
        kind=ChatEventKind.CONTEXT,
        occurred_at=occurred_at,
        timestamp=timestamp,
        messages=tuple(messages),
    )


# ---------------------------------------------------------------------------
def _build_reasoning_event(
    entry_id: str,
    entry_index: int,
    sequence_index: int,
    entry: ChatEntry,
    *,
    fallback_timestamp: str | None,
) -> ReasoningEvent | None:
    segments_raw = entry.reasoning or ()
    if not segments_raw:
        return None
    segments: list[dict[str, Any]] = []
    for segment in segments_raw:
        if isinstance(segment, Mapping):
            segments.append(dict(segment))
    if not segments:
        return None
    timestamp = entry.response_at or entry.prompt_at or fallback_timestamp
    occurred_at = parse_iso_timestamp(timestamp)
    return ReasoningEvent(
        event_id=f"{entry_id}:reasoning",
        entry_id=entry_id,
        entry_index=entry_index,
        sequence_index=sequence_index,
        kind=ChatEventKind.REASONING,
        occurred_at=occurred_at,
        timestamp=timestamp,
        segments=tuple(segments),
    )


def _build_llm_request_event(
    entry_id: str,
    entry_index: int,
    sequence_index: int,
    entry: ChatEntry,
    *,
    fallback_timestamp: str | None,
) -> LlmRequestEvent | None:
    messages, sequence = _extract_llm_request_details(entry)
    if not messages:
        return None
    timestamp = fallback_timestamp
    occurred_at = parse_iso_timestamp(timestamp)
    return LlmRequestEvent(
        event_id=f"{entry_id}:llm-request",
        entry_id=entry_id,
        entry_index=entry_index,
        sequence_index=sequence_index,
        kind=ChatEventKind.LLM_REQUEST,
        occurred_at=occurred_at,
        timestamp=timestamp,
        messages=messages,
        sequence=sequence,
    )


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
            candidate_sequence = _sanitize_request_sequence(source.get("llm_requests"))
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
    if sequence:
        normalized: list[dict[str, Any]] = []
        for entry_payload in sequence:
            safe_entry = history_json_safe(entry_payload)
            if not isinstance(safe_entry, Mapping):
                continue
            record = dict(safe_entry)
            messages_payload = record.get("messages")
            sanitized_messages = _sanitize_message_list(messages_payload)
            if sanitized_messages:
                record["messages"] = tuple(dict(item) for item in sanitized_messages)
            elif "messages" in record:
                record["messages"] = ()
            normalized.append(record)
        if normalized:
            prepared_sequence = tuple(normalized)

    return tuple(prepared_messages), prepared_sequence


def _iter_llm_request_sources(entry: ChatEntry) -> Iterable[Mapping[str, Any]]:
    diagnostic = entry.diagnostic
    if isinstance(diagnostic, Mapping):
        yield diagnostic
    raw_result = entry.raw_result
    if isinstance(raw_result, Mapping):
        yield raw_result
        diagnostic_raw = raw_result.get("diagnostic")
        if isinstance(diagnostic_raw, Mapping):
            yield diagnostic_raw


def _sanitize_message_list(value: Any) -> tuple[dict[str, Any], ...]:
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
def _build_response_event(
    entry_id: str,
    entry_index: int,
    sequence_index: int,
    entry: ChatEntry,
    *,
    fallback_timestamp: str | None,
) -> ResponseEvent | None:
    text = entry.response or ""
    display_text = entry.display_response or text
    if not text and not display_text:
        return None
    timestamp = entry.response_at or entry.prompt_at or fallback_timestamp
    occurred_at = parse_iso_timestamp(timestamp)
    formatted_timestamp = format_entry_timestamp(timestamp)
    return ResponseEvent(
        event_id=f"{entry_id}:response",
        entry_id=entry_id,
        entry_index=entry_index,
        sequence_index=sequence_index,
        kind=ChatEventKind.RESPONSE,
        occurred_at=occurred_at,
        timestamp=timestamp,
        text=text,
        display_text=display_text,
        formatted_timestamp=formatted_timestamp,
        regenerated=bool(getattr(entry, "regenerated", False)),
        step_index=None,
        is_final=True,
    )


# ---------------------------------------------------------------------------
def _build_step_response_events(
    entry_id: str,
    entry_index: int,
    sequence_counter: itertools.count,
    entry: ChatEntry,
    *,
    final_response_text: str | None,
    fallback_timestamp: str | None,
) -> tuple[ResponseEvent, ...]:
    payloads = _collect_llm_step_payloads(entry)
    if not payloads:
        return ()

    final_text = _normalise_message_text(final_response_text)
    events: list[ResponseEvent] = []
    for position, payload in enumerate(payloads, start=1):
        sequence_index = next(sequence_counter)
        event = _build_step_response_event(
            entry_id,
            entry_index,
            sequence_index,
            payload,
            fallback_timestamp=fallback_timestamp,
            fallback_step_index=position,
        )
        if event is None:
            continue
        event_text = _normalise_message_text(event.display_text or event.text)
        if final_text and event_text == final_text:
            continue
        events.append(event)
    return tuple(events)


def _build_step_response_event(
    entry_id: str,
    entry_index: int,
    sequence_index: int,
    payload: Mapping[str, Any],
    *,
    fallback_timestamp: str | None,
    fallback_step_index: int,
) -> ResponseEvent | None:
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
    timestamp_str = (
        timestamp_raw.strip()
        if isinstance(timestamp_raw, str) and timestamp_raw.strip()
        else None
    )
    occurred_at = parse_iso_timestamp(timestamp_str or fallback_timestamp)
    formatted_timestamp = (
        format_entry_timestamp(timestamp_str)
        if timestamp_str
        else ""
    )

    step_raw = payload.get("step")
    step_index: int | None = None
    if isinstance(step_raw, (int, float)):
        step_index = int(step_raw)
    elif isinstance(step_raw, str):
        with suppress(ValueError):
            step_index = int(step_raw.strip())
    if step_index is None:
        step_index = fallback_step_index

    event_id = f"{entry_id}:response-step:{sequence_index}"
    timestamp_value = timestamp_str or fallback_timestamp
    return ResponseEvent(
        event_id=event_id,
        entry_id=entry_id,
        entry_index=entry_index,
        sequence_index=sequence_index,
        kind=ChatEventKind.RESPONSE,
        occurred_at=occurred_at,
        timestamp=timestamp_value,
        text=text,
        display_text=text,
        formatted_timestamp=formatted_timestamp,
        regenerated=False,
        step_index=step_index,
        is_final=False,
    )


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

    def record(identifier: str | None, payload: Any) -> None:
        if not identifier:
            return
        key = str(identifier)
        if key in requests:
            existing = requests[key]
            if isinstance(existing, Mapping) and isinstance(payload, Mapping):
                if "response" in existing and "response" not in payload:
                    return
        safe_payload = history_json_safe(payload)
        if safe_payload is None:
            return
        requests[key] = safe_payload

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

    potential_sources: list[Mapping[str, Any]] = []
    diagnostic = entry.diagnostic
    if isinstance(diagnostic, Mapping):
        potential_sources.append(diagnostic)
    raw_result = entry.raw_result
    if isinstance(raw_result, Mapping):
        potential_sources.append(raw_result)
        diagnostic_raw = raw_result.get("diagnostic")
        if isinstance(diagnostic_raw, Mapping):
            potential_sources.append(diagnostic_raw)

    for source in potential_sources:
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


# ---------------------------------------------------------------------------
def _iter_tool_payloads(tool_results: Sequence[Any] | None) -> Iterable[Mapping[str, Any]]:
    if not tool_results:
        return ()
    ordered = sort_tool_payloads(tool_results)
    result: list[Mapping[str, Any]] = []
    for payload in ordered:
        if isinstance(payload, Mapping):
            result.append(payload)
    return tuple(result)


def _build_tool_call_event(
    entry_id: str,
    entry_index: int,
    sequence_index: int,
    tool_index: int,
    payload: Mapping[str, Any],
    requests: Mapping[str, Any],
    *,
    fallback_timestamp: str | None,
) -> ToolCallEvent:
    summary = summarize_tool_payload(tool_index, payload)
    safe_payload = history_json_safe(payload)
    timestamp = _extract_tool_timestamp(payload) or fallback_timestamp
    occurred_at = parse_iso_timestamp(timestamp)
    call_identifier = _extract_tool_identifier(payload)
    request_payload: Any | None = None
    if call_identifier is not None:
        request_payload = requests.get(call_identifier)
    if request_payload is None:
        request_payload = requests.get(str(tool_index))
    if request_payload is None:
        request_payload = _synthesise_tool_request(payload, summary)
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
    return ToolCallEvent(
        event_id=f"{entry_id}:tool:{tool_index}",
        entry_id=entry_id,
        entry_index=entry_index,
        sequence_index=sequence_index,
        kind=ChatEventKind.TOOL_CALL,
        occurred_at=occurred_at,
        timestamp=timestamp,
        summary=summary,
        call_identifier=call_identifier,
        raw_payload=safe_payload,
        llm_request=request_payload,
    )


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
            "name": (summary.tool_name if summary else ""),
            "arguments": dict(safe_arguments),
        }
    }

    if summary and summary.tool_name:
        request["tool_call"]["name"] = summary.tool_name
    else:
        for key in ("tool_name", "name", "tool"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                request["tool_call"]["name"] = value.strip()
                break

    step_value = payload.get("step")
    if step_value is not None:
        request["step"] = step_value

    return history_json_safe(request)


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
def _build_raw_payload_event(
    entry_id: str,
    entry_index: int,
    sequence_index: int,
    entry: ChatEntry,
    *,
    fallback_timestamp: str | None,
) -> RawPayloadEvent | None:
    if entry.raw_result is None:
        return None
    timestamp = entry.response_at or entry.prompt_at or fallback_timestamp
    occurred_at = parse_iso_timestamp(timestamp)
    safe_payload = history_json_safe(entry.raw_result)
    return RawPayloadEvent(
        event_id=f"{entry_id}:raw",
        entry_id=entry_id,
        entry_index=entry_index,
        sequence_index=sequence_index,
        kind=ChatEventKind.RAW_PAYLOAD,
        occurred_at=occurred_at,
        timestamp=timestamp,
        payload=safe_payload,
    )


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
    "ChatEventKind",
    "ChatEvent",
    "PromptEvent",
    "ContextEvent",
    "ReasoningEvent",
    "ResponseEvent",
    "LlmRequestEvent",
    "ToolCallEvent",
    "RawPayloadEvent",
    "SystemMessageEvent",
    "EntryTimeline",
    "ConversationTimeline",
    "build_conversation_timeline",
]
