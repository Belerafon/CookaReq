"""Event-oriented view model for the agent chat transcript."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import itertools
from typing import Any, Iterable, Mapping, Sequence
import datetime as _dt

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
    TOOL_CALL = "tool_call"
    RAW_PAYLOAD = "raw_payload"
    SYSTEM_MESSAGE = "system_message"


_EVENT_DISPLAY_ORDER: dict[ChatEventKind, int] = {
    ChatEventKind.PROMPT: 0,
    ChatEventKind.CONTEXT: 1,
    ChatEventKind.REASONING: 2,
    ChatEventKind.RESPONSE: 3,
    ChatEventKind.TOOL_CALL: 4,
    ChatEventKind.RAW_PAYLOAD: 5,
    ChatEventKind.SYSTEM_MESSAGE: 6,
}


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


def _event_sort_key(event: ChatEvent) -> tuple[int, int, Any, int]:
    order = _EVENT_DISPLAY_ORDER.get(event.kind, 99)
    occurred = event.occurred_at
    if occurred is None:
        return (order, 1, event.sequence_index, 0)
    return (order, 0, occurred, event.sequence_index)


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


@dataclass(slots=True)
class ToolCallEvent(ChatEvent):
    """Diagnostic information about a single tool call."""

    summary: ToolCallSummary
    call_identifier: str | None
    raw_payload: Any


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
    context: ContextEvent | None
    reasoning: ReasoningEvent | None
    tool_calls: tuple[ToolCallEvent, ...]
    raw_payload: RawPayloadEvent | None
    system_messages: tuple[SystemMessageEvent, ...]
    layout_hints: dict[str, int]
    can_regenerate: bool

    @property
    def events(self) -> tuple[ChatEvent, ...]:
        """Return all events for the entry preserving chronological order."""

        ordered: list[ChatEvent] = [self.prompt]
        if self.context is not None:
            ordered.append(self.context)
        if self.reasoning is not None:
            ordered.append(self.reasoning)
        ordered.extend(self.tool_calls)
        if self.response is not None:
            ordered.append(self.response)
        if self.raw_payload is not None:
            ordered.append(self.raw_payload)
        ordered.extend(self.system_messages)
        ordered.sort(key=_event_sort_key)
        return tuple(ordered)


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

    for entry_index, entry in enumerate(conversation.entries):
        entry_id = f"{conversation.conversation_id}:{entry_index}"
        prompt_event = _build_prompt_event(
            entry_id, entry_index, next(sequence_counter), entry
        )
        context_event = _build_context_event(
            entry_id, entry_index, next(sequence_counter), entry
        )
        reasoning_event = _build_reasoning_event(
            entry_id, entry_index, next(sequence_counter), entry
        )
        response_event = _build_response_event(
            entry_id,
            entry_index,
            next(sequence_counter),
            entry,
        )
        tool_call_events = tuple(
            _build_tool_call_event(
                entry_id,
                entry_index,
                next(sequence_counter),
                tool_index,
                payload,
            )
            for tool_index, payload in enumerate(
                _iter_tool_payloads(entry.tool_results), start=1
            )
        )
        raw_payload_event = _build_raw_payload_event(
            entry_id, entry_index, next(sequence_counter), entry
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
            context=context_event,
            reasoning=reasoning_event,
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
) -> PromptEvent:
    occurred_at = parse_iso_timestamp(entry.prompt_at)
    formatted_timestamp = format_entry_timestamp(entry.prompt_at)
    timestamp = entry.prompt_at
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
    timestamp = entry.prompt_at or entry.response_at
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
    timestamp = entry.prompt_at or entry.response_at
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
def _build_response_event(
    entry_id: str,
    entry_index: int,
    sequence_index: int,
    entry: ChatEntry,
) -> ResponseEvent | None:
    text = entry.response or ""
    display_text = entry.display_response or text
    if not text and not display_text:
        return None
    timestamp = entry.response_at or entry.prompt_at
    occurred_at = parse_iso_timestamp(timestamp)
    formatted_timestamp = format_entry_timestamp(entry.response_at or entry.prompt_at)
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
    )


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
) -> ToolCallEvent:
    summary = summarize_tool_payload(tool_index, payload)
    safe_payload = history_json_safe(payload)
    timestamp = _extract_tool_timestamp(payload)
    occurred_at = parse_iso_timestamp(timestamp)
    call_identifier = _extract_tool_identifier(payload)
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
    )


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
    for key in ("tool_call_id", "call_id", "id"):
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
) -> RawPayloadEvent | None:
    if entry.raw_result is None:
        return None
    timestamp = entry.response_at or entry.prompt_at
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
    "ToolCallEvent",
    "RawPayloadEvent",
    "SystemMessageEvent",
    "EntryTimeline",
    "ConversationTimeline",
    "build_conversation_timeline",
]
