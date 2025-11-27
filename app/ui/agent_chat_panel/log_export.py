from __future__ import annotations

import json
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ...i18n import _
from ...llm.spec import SYSTEM_PROMPT
from ..chat_entry import ChatConversation
from ..text import normalize_for_display
from .time_formatting import format_entry_timestamp
from .view_model import (
    AgentResponse,
    ConversationTimeline,
    TimestampInfo,
    TranscriptEntry,
    build_conversation_timeline,
)


_SYSTEM_PROMPT_TEXT = str(SYSTEM_PROMPT).strip()
SYSTEM_PROMPT_PLACEHOLDER = "<system prompt repeated – omitted>"


def _looks_like_system_prompt(text: str) -> bool:
    """Return ``True`` when *text* matches or is a truncation of the system prompt."""

    if not _SYSTEM_PROMPT_TEXT:
        return False

    stripped = text.strip()
    if not stripped:
        return False

    if stripped.startswith(_SYSTEM_PROMPT_TEXT):
        return True

    trimmed = stripped.rstrip("…")
    if trimmed and _SYSTEM_PROMPT_TEXT.startswith(trimmed):
        # Treat long truncated strings (for example after history sanitisation) as a
        # match so repeated prompts can still be detected and replaced with the
        # placeholder.
        return len(trimmed) >= len(_SYSTEM_PROMPT_TEXT) // 2

    return False


@dataclass(slots=True)
class _PlainEvent:
    """Single entry rendered in the plain transcript timeline."""

    timestamp: str
    label: str
    text: str


def _format_timestamp_label(info: TimestampInfo | None) -> str:
    """Return display label for *info* consistent with the transcript UI."""
    if info is None:
        return _("not recorded")
    if info.formatted:
        return normalize_for_display(info.formatted)
    if info.raw:
        return normalize_for_display(info.raw)
    if info.missing:
        return _("not recorded")
    return _("not recorded")


def _format_iso_timestamp(value: str | None, fallback: TimestampInfo | None) -> str:
    """Return formatted timestamp derived from ISO *value* or *fallback*."""
    if value:
        formatted = format_entry_timestamp(value)
        if formatted:
            return normalize_for_display(formatted)
        return normalize_for_display(value)
    return _format_timestamp_label(fallback)


def _format_tool_timestamp(
    summary: Any, fallback: TimestampInfo | None
) -> str:
    """Return formatted timestamp for a tool call *summary*."""
    for candidate in (
        getattr(summary, "completed_at", None),
        getattr(summary, "last_observed_at", None),
        getattr(summary, "started_at", None),
    ):
        if isinstance(candidate, str) and candidate.strip():
            return _format_iso_timestamp(candidate, fallback)
    return _format_timestamp_label(fallback)


def _collect_agent_plain_events(entry: TranscriptEntry) -> list[_PlainEvent]:
    """Return ordered plain-text events describing the agent turn."""
    turn = entry.agent_turn
    events: list[_PlainEvent] = []
    last_text: str | None = None

    def append_event(
        label: str,
        text: str,
        timestamp: str,
        *,
        track_duplicate: bool = True,
        allow_empty: bool = False,
    ) -> None:
        nonlocal last_text
        if not text and not allow_empty:
            return
        if track_duplicate and text == last_text:
            return
        events.append(
            _PlainEvent(
                timestamp=timestamp,
                label=normalize_for_display(label),
                text=text,
            )
        )
        if track_duplicate and text:
            last_text = text

    if turn is not None:
        timestamp_fallback = turn.timestamp
        fallback_response = normalize_for_display(entry.entry.response or "")
        fallback_display = normalize_for_display(entry.entry.display_response or "")

        def append_response_event(response: AgentResponse, label: str, info: TimestampInfo) -> None:
            raw_text = response.text or ""
            raw_display = response.display_text or ""
            normalized_text = normalize_for_display(raw_text) if raw_text else ""
            normalized_display = (
                normalize_for_display(raw_display) if raw_display else ""
            )
            content = normalized_text or normalized_display
            if not content:
                return
            if (
                not normalized_text
                and not fallback_response
                and content == fallback_display
            ):
                return
            append_event(label, content, _format_timestamp_label(info))

        def response_label(response: AgentResponse) -> str:
            if response.is_final:
                return _("Agent:")
            if response.step_index is not None:
                return _("Agent (step {index}):").format(index=response.step_index)
            return _("Agent:")

        for event in turn.events:
            if event.kind == "response" and event.response is not None:
                info = event.timestamp or timestamp_fallback
                append_response_event(
                    event.response,
                    response_label(event.response),
                    info,
                )
            elif event.kind == "tool" and event.tool_call is not None:
                summary = event.tool_call.summary
                label = _(
                    "Agent: tool call {index}: {tool} — {status}"
                ).format(
                    index=summary.index,
                    tool=summary.tool_name,
                    status=summary.status,
                )
                bullet_lines = [
                    "• " + normalize_for_display(line)
                    for line in getattr(summary, "bullet_lines", ())
                    if line
                ]
                text = "\n".join(bullet_lines)
                timestamp_label = _format_timestamp_label(event.timestamp or timestamp_fallback)
                append_event(
                    label,
                    text,
                    timestamp_label,
                    track_duplicate=False,
                    allow_empty=True,
                )

        if events:
            return events

        fallback = normalize_for_display(
            entry.entry.response or entry.entry.display_response or ""
        )
        if fallback:
            append_event(
                _("Agent:"),
                fallback,
                _format_iso_timestamp(entry.entry.response_at, timestamp_fallback),
            )
            return events

        for detail in turn.tool_calls:
            summary = detail.summary
            label = _(
                "Agent: tool call {index}: {tool} — {status}"
            ).format(
                index=summary.index,
                tool=summary.tool_name,
                status=summary.status,
            )
            bullet_lines = [
                "• " + normalize_for_display(line)
                for line in getattr(summary, "bullet_lines", ())
                if line
            ]
            text = "\n".join(bullet_lines)
            append_event(
                label,
                text,
                _format_tool_timestamp(summary, timestamp_fallback),
                track_duplicate=False,
                allow_empty=True,
            )

    return events


def compose_transcript_text(
    conversation: ChatConversation | None,
    *,
    timeline: ConversationTimeline | None = None,
) -> str:
    """Return the plain conversation transcript for *conversation*."""
    if conversation is None:
        return _("Start chatting with the agent to see responses here.")
    if not conversation.entries:
        return _("This chat does not have any messages yet. Send one to get started.")

    if timeline is None:
        timeline = build_conversation_timeline(conversation)
    if not timeline.entries:
        return _("This chat does not have any messages yet. Send one to get started.")

    blocks: list[str] = []
    indent = "    "

    for idx, entry in enumerate(timeline.entries, start=1):
        prompt_message = entry.prompt
        prompt_text = normalize_for_display(
            (prompt_message.text if prompt_message is not None else entry.entry.prompt)
            or ""
        )
        prompt_timestamp = _format_timestamp_label(
            prompt_message.timestamp if prompt_message is not None else None
        )
        lines: list[str] = []
        header = f"{idx}. [{prompt_timestamp}] " + _("You:")
        lines.append(header)
        if prompt_text:
            lines.append(textwrap.indent(prompt_text, indent))

        events = _collect_agent_plain_events(entry)
        if events:
            for event in events:
                lines.append("")
                lines.append(f"[{event.timestamp}] {event.label}")
                if event.text:
                    lines.append(textwrap.indent(event.text, indent))
        else:
            fallback_timestamp = _format_iso_timestamp(
                getattr(entry.entry, "response_at", None), None
            )
            lines.append("")
            lines.append(f"[{fallback_timestamp}] " + _("Agent:"))

        blocks.append("\n".join(part for part in lines if part is not None))

    return "\n\n".join(blocks)


def _omit_repeated_system_prompt(
    value: Any, *, seen_prompt: bool = False
) -> tuple[Any, bool]:
    sanitized, updated = _strip_repeated_system_prompt(
        value, seen_prompt=seen_prompt
    )
    return sanitized, updated


def _strip_repeated_system_prompt(
    value: Any, *, seen_prompt: bool
) -> tuple[Any, bool]:
    if isinstance(value, str) and _looks_like_system_prompt(value):
        if seen_prompt:
            return SYSTEM_PROMPT_PLACEHOLDER, True

        stripped = value.strip()
        trimmed = stripped.rstrip("…")
        if trimmed and _SYSTEM_PROMPT_TEXT.startswith(trimmed):
            # Rehydrate truncated prompts so the full text appears once in the log.
            return _SYSTEM_PROMPT_TEXT, True

        prompt_index = value.find(_SYSTEM_PROMPT_TEXT)
        # Treat leading whitespace-only prefixes (for example, newlines) as part of
        # the prompt section so that appended business context is preserved.
        if prompt_index != -1 and value[:prompt_index].strip() == "":
            return value, True

        return value, seen_prompt

    if isinstance(value, Mapping):
        current_seen = seen_prompt
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            cleaned, current_seen = _strip_repeated_system_prompt(
                item, seen_prompt=current_seen
            )
            sanitized[key] = cleaned
        return sanitized, current_seen

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        current_seen = seen_prompt
        items: list[Any] = []
        for item in value:
            cleaned, current_seen = _strip_repeated_system_prompt(
                item, seen_prompt=current_seen
            )
            items.append(cleaned)
        if isinstance(value, tuple):
            return tuple(items), current_seen
        if isinstance(value, list):
            return items, current_seen
        try:
            return type(value)(items), current_seen
        except Exception:  # pragma: no cover - defensive
            return items, current_seen

    return value, seen_prompt


def compose_transcript_log_text(
    conversation: ChatConversation | None,
    *,
    timeline: ConversationTimeline | None = None,
) -> str:
    """Return the detailed diagnostic log for *conversation*."""
    if conversation is None:
        return _("Start chatting with the agent to see responses here.")
    if not conversation.entries:
        return _("This chat does not have any messages yet. Send one to get started.")

    if timeline is None:
        timeline = build_conversation_timeline(conversation)

    def format_timestamp_info(info: TimestampInfo | None) -> str:
        return _format_timestamp_label(info)

    def _normalise_json_value(value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith(("{", "[")):
                try:
                    decoded = json.loads(stripped)
                except (TypeError, ValueError):
                    return value
                return _normalise_json_value(decoded)
            return value
        if isinstance(value, Mapping):
            return {
                str(key): _normalise_json_value(val)
                for key, val in value.items()
            }
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            return [_normalise_json_value(item) for item in value]
        return value

    def format_json_block(value: Any) -> str:
        if value is None:
            return _("(none)")
        normalised = _normalise_json_value(value)
        if isinstance(normalised, str):
            text_value = normalised
        else:
            try:
                text_value = json.dumps(
                    normalised,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            except (TypeError, ValueError):
                text_value = str(normalised)
        return normalize_for_display(text_value)

    def indent_block(value: str, *, prefix: str = "    ") -> str:
        return textwrap.indent(value, prefix)

    def describe_agent_response(
        response: AgentResponse,
        turn_timestamp: TimestampInfo | None,
    ) -> list[str]:
        response_timestamp = (
            response.timestamp
            if not response.timestamp.missing
            else turn_timestamp
        )
        timestamp_label = format_timestamp_info(response_timestamp)
        if not timestamp_label and turn_timestamp is not None and turn_timestamp.missing:
            timestamp_label = _("not recorded")
        if not response.is_final and response.step_index is not None:
            label = _("Agent (step {index}):").format(index=response.step_index)
        else:
            label = _("Agent:")
        header = _("[{timestamp}] {label}").format(
            timestamp=timestamp_label,
            label=label,
        )
        lines = [header]
        text_value = normalize_for_display(response.display_text or response.text or "")
        if text_value:
            lines.append(indent_block(text_value))
        return lines

    seen_system_prompt = False
    blocks: list[str] = []
    for entry in timeline.entries:
        prompt = entry.prompt
        prompt_timestamp = format_timestamp_info(
            prompt.timestamp if prompt is not None else None
        )
        if prompt is not None:
            header = _("[{timestamp}] You:").format(timestamp=prompt_timestamp)
            blocks.append(header)
            text_value = normalize_for_display(prompt.text)
            if text_value:
                blocks.append(indent_block(text_value))
        if entry.context_messages:
            header = _("[{timestamp}] Context messages:").format(
                timestamp=prompt_timestamp
            )
            blocks.append(header)
            sanitized_context, seen_system_prompt = _strip_repeated_system_prompt(
                entry.context_messages, seen_prompt=seen_system_prompt
            )
            blocks.append(indent_block(format_json_block(sanitized_context)))

        turn = entry.agent_turn
        if turn is not None:
            for event in turn.events:
                if event.kind == "response" and event.response is not None:
                    blocks.extend(
                        describe_agent_response(event.response, turn.timestamp)
                    )
                elif event.kind == "tool" and event.tool_call is not None:
                    details = event.tool_call
                    summary = details.summary
                    tool_name = normalize_for_display(
                        summary.tool_name or _("Unnamed tool")
                    )
                    status_label = normalize_for_display(
                        summary.status or _("returned data")
                    )
                    header = _(
                        "[{timestamp}] Tool call {index}: {tool} — {status}"
                    ).format(
                        timestamp=format_timestamp_info(event.timestamp),
                        index=summary.index,
                        tool=tool_name,
                        status=status_label,
                    )
                    blocks.append(header)
                    if summary.started_at:
                        blocks.append(
                            indent_block(
                                _("Started at {timestamp}").format(
                                    timestamp=summary.started_at
                                )
                            )
                        )
                    if summary.completed_at:
                        blocks.append(
                            indent_block(
                                _("Completed at {timestamp}").format(
                                    timestamp=summary.completed_at
                                )
                            )
                        )
                    if summary.bullet_lines:
                        for bullet in summary.bullet_lines:
                            if bullet:
                                blocks.append(
                                    indent_block(normalize_for_display(bullet))
                                )
                    payload, seen_system_prompt = _omit_repeated_system_prompt(
                        details.raw_data, seen_prompt=seen_system_prompt
                    )
                    blocks.append(indent_block(format_json_block(payload)))
                    if details.call_identifier:
                        identifier_line = _(
                            "Call identifier: {identifier}"
                        ).format(
                            identifier=normalize_for_display(details.call_identifier)
                        )
                        blocks.append(indent_block(identifier_line))

            if turn.reasoning:
                header = _("[{timestamp}] Model reasoning:").format(
                    timestamp=format_timestamp_info(turn.timestamp)
                )
                blocks.append(header)
                blocks.append(indent_block(format_json_block(turn.reasoning)))

            if turn.llm_request is not None and turn.llm_request.messages:
                payload: dict[str, Any] = {"messages": turn.llm_request.messages}
                if turn.llm_request.sequence is not None:
                    payload["sequence"] = turn.llm_request.sequence
                payload, seen_system_prompt = _omit_repeated_system_prompt(
                    payload, seen_prompt=seen_system_prompt
                )
                header = _("[{timestamp}] LLM request:").format(
                    timestamp=format_timestamp_info(turn.timestamp)
                )
                blocks.append(header)
                blocks.append(indent_block(format_json_block(payload)))

            if turn.raw_payload is not None:
                header = _("[{timestamp}] Raw LLM payload:").format(
                    timestamp=format_timestamp_info(turn.timestamp)
                )
                blocks.append(header)
                raw_payload, seen_system_prompt = _omit_repeated_system_prompt(
                    turn.raw_payload, seen_prompt=seen_system_prompt
                )
                blocks.append(indent_block(format_json_block(raw_payload)))

        for system_message in entry.system_messages:
            header = _("[{timestamp}] System message:").format(
                timestamp=format_timestamp_info(None)
            )
            blocks.append(header)
            text_value = normalize_for_display(getattr(system_message, "message", ""))
            if text_value:
                blocks.append(indent_block(text_value))
            details_payload = getattr(system_message, "details", None)
            if details_payload is not None:
                blocks.append(indent_block(format_json_block(details_payload)))

    return "\n".join(block for block in blocks if block)


__all__ = [
    "compose_transcript_log_text",
    "compose_transcript_text",
    "SYSTEM_PROMPT_PLACEHOLDER",
]
