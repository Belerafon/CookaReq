"""Logging helpers for LLM interactions."""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping, Sequence

from ..telemetry import log_debug_payload, log_event
from .spec import SYSTEM_PROMPT

__all__ = ["log_request", "log_response"]

_PROMPT_PLACEHOLDER_TEXT = (
    "System prompt and tool list were elided by the logging system for brevity, "
    "but were sent to the LLM unchanged."
)

_SYSTEM_SECTION_RE = re.compile(
    r"(<\|start\|>system<\|message\|>)(.*?)(<\|end\|>)",
    re.DOTALL,
)
_DEVELOPER_SECTION_RE = re.compile(
    r"(<\|start\|>developer<\|message\|>)(.*?)(<\|end\|>)",
    re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class PromptSignature:
    """Immutable fingerprint describing repeated prompt sections."""

    format: str
    system_parts: tuple[str, ...]
    tool_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChatPromptAnalysis:
    """Metadata extracted from Chat Completions payloads."""

    signature: PromptSignature | None
    system_indices: tuple[int, ...]
    has_tools: bool


@dataclass(frozen=True, slots=True)
class HarmonyPromptAnalysis:
    """Metadata extracted from Harmony Responses payloads."""

    signature: PromptSignature | None
    system_span: tuple[int, int] | None
    instructions_span: tuple[int, int] | None
    tools_span: tuple[int, int] | None
    has_tools: bool


class _PromptLogState:
    """Remember prompt fingerprints already emitted to the logs."""

    def __init__(self) -> None:
        self._seen_signatures: set[PromptSignature] = set()

    def register(self, signature: PromptSignature | None) -> bool:
        """Return ``True`` when *signature* was logged before."""
        if signature is None:
            return False
        if not signature.system_parts and not signature.tool_names:
            return False
        if signature in self._seen_signatures:
            return True
        self._seen_signatures.add(signature)
        return False

    def reset(self) -> None:
        """Forget previously seen signatures (testing helper)."""
        self._seen_signatures.clear()


_PROMPT_STATE = _PromptLogState()


def _reset_prompt_log_state() -> None:
    """Reset internal cache used to de-duplicate prompt logging."""
    _PROMPT_STATE.reset()


def log_request(payload: Mapping[str, Any]) -> None:
    """Record telemetry for an outbound LLM request."""
    prepared = _prepare_request_payload(payload)
    log_debug_payload("LLM_REQUEST", prepared)
    log_event("LLM_REQUEST", prepared)


def log_response(
    payload: Mapping[str, Any], *, start_time: float | None = None, direction: str = "inbound"
) -> None:
    """Record telemetry for an inbound LLM response."""
    log_event("LLM_RESPONSE", payload, start_time=start_time)
    debug_payload = {"direction": direction, **payload}
    log_debug_payload("LLM_RESPONSE", debug_payload)


def _prepare_request_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a deep-copied payload with repeated prompts collapsed."""
    if not isinstance(payload, Mapping):
        return payload

    sanitized = deepcopy(dict(payload))

    chat_analysis = _analyze_chat_payload(payload)
    if chat_analysis.signature is not None:
        if _PROMPT_STATE.register(chat_analysis.signature):
            _apply_chat_placeholders(sanitized, chat_analysis)
        return sanitized

    harmony_analysis = _analyze_harmony_payload(payload)
    if harmony_analysis.signature is not None:
        if _PROMPT_STATE.register(harmony_analysis.signature):
            _apply_harmony_placeholders(sanitized, harmony_analysis)
        return sanitized

    return sanitized


def _analyze_chat_payload(payload: Mapping[str, Any]) -> ChatPromptAnalysis:
    """Extract metadata describing Chat Completions requests."""
    messages = payload.get("messages")
    if not isinstance(messages, Sequence):
        return ChatPromptAnalysis(signature=None, system_indices=(), has_tools=False)

    indices: list[int] = []
    for idx, raw_message in enumerate(messages):
        if not isinstance(raw_message, Mapping):
            continue
        role = raw_message.get("role")
        if role != "system":
            continue
        content = raw_message.get("content")
        text = _extract_text(content)
        if not text or not text.startswith(SYSTEM_PROMPT):
            continue
        indices.append(idx)

    tool_names = _extract_tool_names(payload.get("tools"))

    if not indices and not tool_names:
        return ChatPromptAnalysis(signature=None, system_indices=(), has_tools=False)

    signature = PromptSignature(
        format="chat",
        system_parts=tuple(SYSTEM_PROMPT for _ in indices),
        tool_names=tool_names,
    )
    return ChatPromptAnalysis(
        signature=signature,
        system_indices=tuple(indices),
        has_tools=bool(tool_names),
    )


def _apply_chat_placeholders(
    payload: Mapping[str, Any], analysis: ChatPromptAnalysis
) -> None:
    """Replace duplicated Chat Completions prompts with a placeholder."""
    messages = payload.get("messages")
    if isinstance(messages, list):
        for index in analysis.system_indices:
            if 0 <= index < len(messages):
                _replace_system_prompt_in_message(messages[index])

    if analysis.has_tools and "tools" in payload:
        payload["tools"] = _PROMPT_PLACEHOLDER_TEXT


def _replace_system_prompt_in_message(message: Mapping[str, Any]) -> None:
    """Trim the base system prompt from *message* preserving contextual tail."""
    if not isinstance(message, dict):
        return
    content = message.get("content")
    text = _extract_text(content)
    if not text or not text.startswith(SYSTEM_PROMPT):
        return

    remainder = text[len(SYSTEM_PROMPT) :]
    new_text = f"{_PROMPT_PLACEHOLDER_TEXT}{remainder}"
    message["content"] = _rebuild_message_content(content, new_text)


def _rebuild_message_content(original: Any, new_text: str) -> Any:
    """Return message content mirroring *original* but with *new_text*."""
    if isinstance(original, list):
        return [{"type": "text", "text": new_text}]
    if isinstance(original, Mapping):
        updated = dict(original)
        if isinstance(updated.get("text"), str):
            updated["text"] = new_text
        else:
            updated["content"] = new_text
        return updated
    return new_text


def _analyze_harmony_payload(payload: Mapping[str, Any]) -> HarmonyPromptAnalysis:
    """Extract metadata describing Harmony Responses requests."""
    prompt = payload.get("input")
    if not isinstance(prompt, str):
        return HarmonyPromptAnalysis(
            signature=None,
            system_span=None,
            instructions_span=None,
            tools_span=None,
            has_tools=False,
        )

    system_match = _SYSTEM_SECTION_RE.search(prompt)
    developer_match = _DEVELOPER_SECTION_RE.search(prompt)

    system_span: tuple[int, int] | None = None
    system_part: str | None = None
    if system_match:
        system_span = (system_match.start(2), system_match.end(2))
        system_part = system_match.group(2)

    instructions_span: tuple[int, int] | None = None
    if developer_match:
        developer_content = developer_match.group(2)
        developer_start = developer_match.start(2)
        if developer_content.startswith("# Instructions\n"):
            after_header_offset = len("# Instructions\n")
            after_header = developer_content[after_header_offset:]
            body_start = developer_start + after_header_offset
            tools_marker = "\n# Tools"
            marker_idx = after_header.find(tools_marker)
            if marker_idx >= 0:
                instructions_text = after_header[:marker_idx]
                tools_block_start = body_start + marker_idx + 1
                tools_span = (tools_block_start, developer_match.end(2))
            else:
                instructions_text = after_header
                tools_span = None
            base_slice = _find_system_prompt_slice(instructions_text)
            if base_slice:
                start, end = base_slice
                instructions_span = (body_start + start, body_start + end)
        else:
            instructions_text = None
            tools_span = (
                (developer_match.start(2), developer_match.end(2))
                if developer_content.startswith("# Tools")
                else None
            )
    else:
        instructions_text = None
        tools_span = None

    tool_names = _extract_tool_names(payload.get("tools"))

    system_parts: list[str] = []
    if system_part:
        system_parts.append(system_part)
    if instructions_span is not None:
        system_parts.append(SYSTEM_PROMPT)

    if not system_parts and not tool_names:
        return HarmonyPromptAnalysis(
            signature=None,
            system_span=None,
            instructions_span=None,
            tools_span=tools_span,
            has_tools=bool(tool_names),
        )

    signature = PromptSignature(
        format="harmony",
        system_parts=tuple(system_parts),
        tool_names=tool_names,
    )
    return HarmonyPromptAnalysis(
        signature=signature,
        system_span=system_span,
        instructions_span=instructions_span,
        tools_span=tools_span,
        has_tools=bool(tool_names),
    )


def _apply_harmony_placeholders(
    payload: Mapping[str, Any], analysis: HarmonyPromptAnalysis
) -> None:
    """Replace duplicated Harmony prompt fragments with a placeholder."""
    prompt = payload.get("input")
    if not isinstance(prompt, str):
        return

    replacements: list[tuple[int, int, str]] = []
    if analysis.tools_span:
        start, end = analysis.tools_span
        replacements.append((start, end, f"# Tools\n{_PROMPT_PLACEHOLDER_TEXT}"))
    if analysis.instructions_span:
        start, end = analysis.instructions_span
        replacements.append((start, end, _PROMPT_PLACEHOLDER_TEXT))
    if analysis.system_span:
        start, end = analysis.system_span
        replacements.append((start, end, _PROMPT_PLACEHOLDER_TEXT))

    if replacements:
        replacements.sort(key=lambda item: item[0], reverse=True)
        new_prompt = prompt
        for start, end, replacement in replacements:
            new_prompt = f"{new_prompt[:start]}{replacement}{new_prompt[end:]}"
        payload["input"] = new_prompt

    if analysis.has_tools and "tools" in payload:
        payload["tools"] = _PROMPT_PLACEHOLDER_TEXT


def _extract_text(content: Any) -> str:
    """Return best-effort textual representation of ``content``."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        text_value = content.get("text")
        if isinstance(text_value, str):
            return text_value
        inner = content.get("content")
        if inner is not None:
            return _extract_text(inner)
        return ""
    if isinstance(content, Sequence) and not isinstance(
        content, (str, bytes, bytearray)
    ):
        parts = [_extract_text(part) for part in content]
        return "".join(part for part in parts if part)
    return ""


def _extract_tool_names(value: Any) -> tuple[str, ...]:
    """Return ordered tool names extracted from ``value``."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    names: list[str] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        name = entry.get("name")
        if not isinstance(name, str):
            function = entry.get("function")
            if isinstance(function, Mapping):
                name = function.get("name")
        if isinstance(name, str):
            names.append(name)
    return tuple(names)


def _find_system_prompt_slice(text: str | None) -> tuple[int, int] | None:
    """Locate the base system prompt within developer instructions."""
    if not text:
        return None
    stripped = text.lstrip()
    if not stripped.startswith(SYSTEM_PROMPT):
        return None
    offset = len(text) - len(stripped)
    start = offset
    end = start + len(SYSTEM_PROMPT)
    return start, end
