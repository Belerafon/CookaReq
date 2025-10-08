"""Helpers responsible for preparing LLM request payloads."""
from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any

from ..telemetry import log_event
from .constants import DEFAULT_MAX_CONTEXT_TOKENS, MIN_MAX_CONTEXT_TOKENS
from .harmony import HARMONY_KNOWLEDGE_CUTOFF, HarmonyPrompt, render_harmony_prompt
from .reasoning import is_reasoning_type, normalise_reasoning_segments
from .response_parser import normalise_tool_calls
from .spec import SYSTEM_PROMPT, TOOLS
from .tokenizer import count_text_tokens
from .types import HistoryTrimResult
from .utils import extract_mapping

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from ..settings import LLMSettings

__all__ = ["LLMRequestBuilder", "PreparedChatRequest"]


@dataclass(frozen=True, slots=True)
class PreparedChatRequest:
    """Container with prepared chat payload."""

    messages: list[dict[str, Any]]
    snapshot: tuple[dict[str, Any], ...] | None
    request_args: dict[str, Any]


class LLMRequestBuilder:
    """Prepare request arguments for the configured LLM backend."""

    def __init__(self, settings: LLMSettings, message_format: str) -> None:
        """Bind the request builder to explicit LLM settings and message format."""
        from ..settings import LLMSettings  # local import to avoid cycles

        if not isinstance(settings, LLMSettings):  # pragma: no cover - defensive
            raise TypeError("settings must be an instance of LLMSettings")
        self.settings = settings
        self._message_format = message_format

    # ------------------------------------------------------------------
    def resolve_temperature(self) -> float | None:
        """Return the user-configured temperature or ``None`` when unset."""
        if getattr(self.settings, "use_custom_temperature", False):
            value = getattr(self.settings, "temperature", None)
            if value is None:
                return None
            try:
                return float(value)
            except (TypeError, ValueError):  # pragma: no cover - defensive
                return None
        return None

    def build_chat_request(
        self,
        conversation: Sequence[Mapping[str, Any]] | None,
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        stream: bool = False,
    ) -> PreparedChatRequest:
        """Return normalized messages and arguments for the chat endpoint."""
        messages = self._prepare_messages(conversation or [])
        snapshot = self._snapshot_messages(messages)
        request_args = self._build_request_args(
            messages,
            tools=tools,
            stream=stream,
        )
        return PreparedChatRequest(
            messages=messages,
            snapshot=snapshot,
            request_args=request_args,
        )

    def build_raw_request_args(
        self,
        messages: Sequence[Mapping[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Expose low-level payload builder for health checks and tests."""
        return self._build_request_args(messages, **kwargs)

    def build_harmony_prompt(
        self, conversation: Sequence[Mapping[str, Any]]
    ) -> HarmonyPrompt:
        """Render a Harmony prompt describing the provided conversation history."""
        system_parts, ordered_messages, _ = self._prepare_history_components(
            conversation
        )
        return render_harmony_prompt(
            instruction_blocks=system_parts,
            history=ordered_messages,
            tools=TOOLS,
            reasoning_level="high",
            current_date=date.today().isoformat(),
            knowledge_cutoff=HARMONY_KNOWLEDGE_CUTOFF,
        )

    # ------------------------------------------------------------------
    def _build_request_args(
        self,
        messages: Sequence[Mapping[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        request_args: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
        }
        if kwargs:
            request_args.update({k: v for k, v in kwargs.items() if v is not None})
        return request_args

    def _snapshot_messages(
        self, messages: Sequence[Mapping[str, Any]]
    ) -> tuple[dict[str, Any], ...] | None:
        try:
            return tuple(json.loads(json.dumps(messages, ensure_ascii=False)))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return tuple(
                dict(message)
                if isinstance(message, Mapping)
                else {"value": message}
                for message in messages
            )

    # ------------------------------------------------------------------
    def _prepare_messages(
        self,
        conversation: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        system_parts, ordered_messages, _ = self._prepare_history_components(
            conversation
        )
        merged_system_message = {
            "role": "system",
            "content": "\n\n".join(
                part for part in system_parts if isinstance(part, str) and part
            ),
        }
        prepared = [merged_system_message, *ordered_messages]
        if self._message_format == "qwen":
            return self._convert_messages_for_qwen(prepared)
        return prepared

    def _prepare_history_components(
        self,
        conversation: Sequence[Mapping[str, Any]],
    ) -> tuple[list[str], list[dict[str, Any]], HistoryTrimResult]:
        sanitized_history = self._sanitise_conversation(conversation)
        limit = self._resolved_max_context_tokens()
        reserved = self._count_tokens(SYSTEM_PROMPT)
        remaining = max(limit - reserved, 0)
        trim_result = self._trim_history(
            sanitized_history,
            remaining_tokens=remaining,
        )
        if trim_result.dropped_messages:
            history_messages_after = len(trim_result.kept_messages)
            log_event(
                "LLM_CONTEXT_TRIMMED",
                {
                    "dropped_messages": trim_result.dropped_messages,
                    "dropped_tokens": trim_result.dropped_tokens,
                    "history_messages_before": trim_result.total_messages,
                    "history_messages_after": history_messages_after,
                    "history_tokens_before": trim_result.total_tokens,
                    "history_tokens_after": trim_result.kept_tokens,
                    "max_context_tokens": limit,
                    "system_prompt_tokens": reserved,
                    "history_token_budget": remaining,
                },
            )
        system_parts: list[str] = [SYSTEM_PROMPT]
        ordered_messages: list[dict[str, Any]] = []
        for message in trim_result.kept_messages:
            role = message.get("role")
            if role == "system":
                content = message.get("content")
                if isinstance(content, str) and content:
                    if self._is_context_snapshot(content):
                        system_parts.append(content)
                        continue
                    ordered_messages.append(message)
                continue
            ordered_messages.append(message)
        return system_parts, ordered_messages, trim_result

    # ------------------------------------------------------------------
    def _sanitise_conversation(
        self,
        conversation: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        if not conversation:
            return []
        sanitized: list[dict[str, Any]] = []
        for message in conversation:
            if isinstance(message, Mapping):
                role = message.get("role")
                content = message.get("content")
            else:  # pragma: no cover - defensive for duck typing
                role = getattr(message, "role", None)
                content = getattr(message, "content", None)
            if role is None:
                continue
            role_str = str(role)
            if role_str not in {"user", "assistant", "tool", "system"}:
                continue
            text = "" if content is None else str(content)
            if role_str in {"assistant", "user"} and not text:
                # OpenRouter serialises empty strings as ``null`` which breaks
                # its request templating.  Substitute a harmless space so the
                # payload remains truthful while staying compatible.
                text = " "
            entry: dict[str, Any] = {
                "role": role_str,
                "content": text,
            }
            if role_str == "assistant":
                tool_calls = (
                    message.get("tool_calls")
                    if isinstance(message, Mapping)
                    else getattr(message, "tool_calls", None)
                )
                normalized_calls = normalise_tool_calls(tool_calls)
                if normalized_calls:
                    entry["tool_calls"] = normalized_calls
                reasoning_value = (
                    message.get("reasoning")
                    if isinstance(message, Mapping)
                    else getattr(message, "reasoning", None)
                )
                normalized_reasoning = normalise_reasoning_segments(reasoning_value)
                if normalized_reasoning:
                    entry["reasoning"] = normalized_reasoning
            elif role_str == "tool":
                if isinstance(message, Mapping):
                    tool_call_id = message.get("tool_call_id")
                    name = message.get("name")
                else:  # pragma: no cover - defensive
                    tool_call_id = getattr(message, "tool_call_id", None)
                    name = getattr(message, "name", None)
                if tool_call_id:
                    entry["tool_call_id"] = str(tool_call_id)
                if name:
                    entry["name"] = str(name)
            sanitized.append(entry)
        return sanitized

    # ------------------------------------------------------------------
    def _convert_messages_for_qwen(
        self, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            entry = {key: value for key, value in message.items() if key != "content"}
            entry["content"] = self._ensure_qwen_segments(message.get("content"))
            converted.append(entry)
        return converted

    def _ensure_qwen_segments(self, content: Any) -> list[dict[str, Any]]:
        if isinstance(content, list):
            segments: list[dict[str, Any]] = []
            for part in content:
                mapping = extract_mapping(part)
                if not mapping:
                    text = self._extract_message_text(part)
                    if text:
                        segments.append({"type": "text", "text": text})
                    continue
                part_type = mapping.get("type") or "text"
                text_value = mapping.get("text")
                if isinstance(text_value, str):
                    segments.append({"type": str(part_type), "text": text_value})
                    continue
                inner = mapping.get("content")
                text = self._extract_message_text(inner)
                if text:
                    segments.append({"type": str(part_type), "text": text})
            if segments:
                return segments
        text_payload = self._extract_message_text(content)
        return [{"type": "text", "text": text_payload}]

    def _extract_message_text(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, Mapping):
            type_field = content.get("type")
            if self._should_skip_segment(type_field):
                return ""
            text_value = content.get("text")
            if isinstance(text_value, str):
                return text_value
            return self._extract_message_text(content.get("content"))
        if isinstance(content, Sequence) and not isinstance(
            content, (str, bytes, bytearray)
        ):
            parts = [self._extract_message_text(part) for part in content]
            return "".join(part for part in parts if part)
        type_attr = getattr(content, "type", None)
        if self._should_skip_segment(type_attr):
            return ""
        text_attr = getattr(content, "text", None)
        if isinstance(text_attr, str):
            return text_attr
        return self._extract_message_text(getattr(content, "content", None))

    def _should_skip_segment(self, segment_type: Any) -> bool:
        return is_reasoning_type(segment_type)

    # ------------------------------------------------------------------
    def _resolved_max_context_tokens(self) -> int:
        limit = getattr(self.settings, "max_context_tokens", None)
        if limit is None or limit <= 0:
            return DEFAULT_MAX_CONTEXT_TOKENS
        if limit < MIN_MAX_CONTEXT_TOKENS:
            return MIN_MAX_CONTEXT_TOKENS
        return limit

    def _count_tokens(self, text: Any) -> int:
        result = count_text_tokens(text, model=self.settings.model)
        return result.tokens or 0

    def _is_context_snapshot(self, content: str) -> bool:
        stripped = content.lstrip()
        return stripped.startswith("[Workspace context]")

    def _trim_history(
        self,
        history: list[dict[str, Any]],
        *,
        remaining_tokens: int,
    ) -> HistoryTrimResult:
        if not history:
            return HistoryTrimResult(
                kept_messages=[],
                dropped_messages=0,
                dropped_tokens=0,
                total_messages=0,
                total_tokens=0,
                kept_tokens=0,
            )
        total_tokens = sum(self._count_tokens(msg["content"]) for msg in history)
        total_messages = len(history)
        if remaining_tokens <= 0:
            return HistoryTrimResult(
                kept_messages=[],
                dropped_messages=total_messages,
                dropped_tokens=total_tokens,
                total_messages=total_messages,
                total_tokens=total_tokens,
                kept_tokens=0,
            )
        kept_rev: list[dict[str, Any]] = []
        kept_tokens = 0
        for message in reversed(history):
            tokens = self._count_tokens(message["content"])
            if tokens > remaining_tokens and kept_rev:
                break
            kept_rev.append(message)
            kept_tokens += tokens
            remaining_tokens = max(remaining_tokens - tokens, 0)
        kept = list(reversed(kept_rev))
        dropped_messages = total_messages - len(kept)
        dropped_tokens = total_tokens - kept_tokens
        return HistoryTrimResult(
            kept_messages=kept,
            dropped_messages=dropped_messages,
            dropped_tokens=dropped_tokens,
            total_messages=total_messages,
            total_tokens=total_tokens,
            kept_tokens=kept_tokens,
        )
