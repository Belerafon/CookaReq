from __future__ import annotations

import json
import textwrap
from collections.abc import Mapping, Sequence
from typing import Any

from ...i18n import _
from ...llm.spec import SYSTEM_PROMPT
from ..chat_entry import ChatConversation
from ..text import normalize_for_display
from .tool_summaries import render_tool_summaries_plain, summarize_tool_results
from .view_model import (
    AgentResponse,
    AgentTurn,
    TimestampInfo,
    TranscriptEntry,
    build_conversation_timeline,
)


_SYSTEM_PROMPT_TEXT = str(SYSTEM_PROMPT).strip()
SYSTEM_PROMPT_PLACEHOLDER = "<system prompt repeated – omitted>"


def compose_transcript_text(conversation: ChatConversation | None) -> str:
    """Return the plain conversation transcript for *conversation*."""

    if conversation is None:
        return _("Start chatting with the agent to see responses here.")
    if not conversation.entries:
        return _("This chat does not have any messages yet. Send one to get started.")

    timeline = build_conversation_timeline(conversation)
    if not timeline.entries:
        return _("This chat does not have any messages yet. Send one to get started.")

    blocks: list[str] = []
    for idx, entry in enumerate(timeline.entries, start=1):
        prompt = entry.prompt.text if entry.prompt is not None else entry.entry.prompt
        prompt_text = normalize_for_display(prompt or "")
        response_text = _compose_agent_plain_text(entry)
        block = (
            f"{idx}. "
            + _("You:")
            + f"\n{prompt_text}\n\n"
            + _("Agent:")
            + f"\n{response_text}"
        )
        blocks.append(block)
    return "\n\n".join(blocks)


def _compose_agent_plain_text(entry: TranscriptEntry) -> str:
    turn = entry.agent_turn
    parts: list[str] = []

    response_text = _select_agent_response_text(turn, entry)
    if response_text:
        parts.append(response_text)

    tool_summary = _compose_tool_summary_text(entry)
    if tool_summary:
        parts.append(tool_summary)

    return "\n\n".join(part for part in parts if part)


def _select_agent_response_text(
    turn: AgentTurn | None, entry: TranscriptEntry
) -> str:
    if turn is not None:
        candidate = _extract_response_from_turn(turn)
        if candidate:
            return normalize_for_display(candidate)

    fallback = entry.entry.response or entry.entry.display_response
    return normalize_for_display(fallback or "")


def _extract_response_from_turn(turn: AgentTurn) -> str:
    if turn.final_response is not None:
        candidate = turn.final_response.text or turn.final_response.display_text or ""
        if candidate:
            return candidate

    for response in reversed(turn.streamed_responses):
        candidate = response.text or response.display_text
        if candidate:
            return candidate
    return ""


def _compose_tool_summary_text(entry: TranscriptEntry) -> str:
    turn = entry.agent_turn
    if turn is not None and turn.tool_calls:
        summaries = [details.summary for details in turn.tool_calls if details.summary]
        if summaries:
            return render_tool_summaries_plain(summaries)

    return render_tool_summaries_plain(
        summarize_tool_results(entry.entry.tool_results)
    )


def _omit_repeated_system_prompt(
    payload: Mapping[str, Any], *, seen_prompt: bool = False
) -> tuple[dict[str, Any], bool]:
    sanitized, updated = _strip_repeated_system_prompt(
        dict(payload), seen_prompt=seen_prompt
    )
    if isinstance(sanitized, Mapping):
        return dict(sanitized), updated
    return dict(payload), updated


def _strip_repeated_system_prompt(
    value: Any, *, seen_prompt: bool
) -> tuple[Any, bool]:
    if not _SYSTEM_PROMPT_TEXT:
        return value, seen_prompt

    if isinstance(value, str):
        if value.strip() == _SYSTEM_PROMPT_TEXT:
            if seen_prompt:
                return SYSTEM_PROMPT_PLACEHOLDER, True
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


def compose_transcript_log_text(conversation: ChatConversation | None) -> str:
    """Return the detailed diagnostic log for *conversation*."""

    if conversation is None:
        return _("Start chatting with the agent to see responses here.")
    if not conversation.entries:
        return _("This chat does not have any messages yet. Send one to get started.")

    timeline = build_conversation_timeline(conversation)

    def format_timestamp_info(info: TimestampInfo | None) -> str:
        if info is None:
            return _("not recorded")
        if info.formatted:
            return normalize_for_display(info.formatted)
        if info.raw:
            return normalize_for_display(info.raw)
        return _("not recorded")

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
            for response in turn.streamed_responses:
                blocks.extend(describe_agent_response(response, turn.timestamp))
            if turn.final_response is not None:
                blocks.extend(describe_agent_response(turn.final_response, turn.timestamp))

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

            for details in turn.tool_calls:
                summary = details.summary
                tool_name = normalize_for_display(summary.tool_name or _("Unnamed tool"))
                status_label = normalize_for_display(summary.status or _("returned data"))
                header = _("[{timestamp}] Tool call {index}: {tool} — {status}").format(
                    timestamp=format_timestamp_info(turn.timestamp),
                    index=summary.index,
                    tool=tool_name,
                    status=status_label,
                )
                blocks.append(header)
                if summary.bullet_lines:
                    for bullet in summary.bullet_lines:
                        if bullet:
                            blocks.append(indent_block(normalize_for_display(bullet)))
                blocks.append(indent_block(format_json_block(details.raw_payload)))
                if details.llm_request is not None:
                    blocks.append(indent_block(format_json_block(details.llm_request)))
                if details.call_identifier:
                    identifier_line = _("Call identifier: {identifier}").format(
                        identifier=normalize_for_display(details.call_identifier)
                    )
                    blocks.append(indent_block(identifier_line))

            if turn.raw_payload is not None:
                header = _("[{timestamp}] Raw LLM payload:").format(
                    timestamp=format_timestamp_info(turn.timestamp)
                )
                blocks.append(header)
                blocks.append(indent_block(format_json_block(turn.raw_payload)))

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
