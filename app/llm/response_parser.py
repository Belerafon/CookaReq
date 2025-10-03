"""Utilities for parsing LLM responses."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..telemetry import log_debug_payload, log_event
from ..util.cancellation import CancellationEvent, OperationCancelledError
from ..util.json import make_json_safe
from .reasoning import (
    ReasoningFragment,
    collect_reasoning_fragments,
    extract_reasoning_entries,
    is_reasoning_type,
    merge_reasoning_fragments,
)
from .types import LLMReasoningSegment, LLMToolCall
from .utils import extract_mapping
from .validation import ToolValidationError

__all__ = [
    "LLMResponseParser",
    "normalise_tool_calls",
]


@dataclass(frozen=True, slots=True)
class _ToolArgumentRecovery:
    """Describe a successful recovery from a malformed tool argument payload."""

    arguments: Mapping[str, Any]
    classification: str
    fragments: int
    recovered_fragment_index: int
    empty_fragment_count: int


def _extract_tool_argument_mapping(arguments: Any) -> Mapping[str, Any] | None:
    """Return a mapping for tool arguments without relying on ``__dict__``."""

    if isinstance(arguments, Mapping):
        return arguments
    for attr in ("model_dump", "dict"):
        method = getattr(arguments, attr, None)
        if callable(method):
            try:
                data = method()
            except Exception:  # pragma: no cover - defensive
                continue
            if isinstance(data, Mapping):
                return data
    if is_dataclass(arguments):
        try:
            data = asdict(arguments)
        except Exception:  # pragma: no cover - defensive
            data = None
        if isinstance(data, Mapping):
            return data
    data = getattr(arguments, "_data", None)
    if isinstance(data, Mapping):
        return data
    return None


def _stringify_tool_arguments(arguments: Any) -> str:
    """Coerce tool arguments into a JSON text payload without dropping data."""

    if isinstance(arguments, str):
        return arguments or "{}"
    if isinstance(arguments, bytes):
        decoded = arguments.decode("utf-8", errors="replace")
        return decoded or "{}"
    if arguments is None:
        return "{}"

    fallback_source = arguments if arguments is not None else "{}"
    fallback = str(fallback_source).strip()

    def _dump(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return ""

    def _prefer(text: str) -> str | None:
        if not text:
            return None
        candidate = text.strip()
        if not candidate:
            return None
        if candidate not in {"{}", "[]"}:
            return text
        if fallback and fallback[0] in "[{" and fallback not in {"{}", "[]"}:
            return fallback
        return candidate

    mapping = _extract_tool_argument_mapping(arguments)
    if mapping:
        safe_mapping = make_json_safe(
            mapping,
            stringify_keys=True,
            coerce_sequences=True,
            default=str,
        )
        preferred = _prefer(_dump(safe_mapping))
        if preferred is not None:
            return preferred

    if isinstance(arguments, Sequence) and not isinstance(
        arguments, (str, bytes, bytearray)
    ):
        safe_sequence = make_json_safe(
            arguments,
            stringify_keys=True,
            coerce_sequences=True,
            default=str,
        )
        preferred = _prefer(_dump(safe_sequence))
        if preferred is not None:
            return preferred

    preferred = _prefer(_dump(arguments))
    if preferred is not None:
        return preferred

    return fallback or "{}"


def normalise_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    """Normalize tool call payloads into the OpenAI function schema."""

    if not tool_calls:
        return []
    if isinstance(tool_calls, Mapping):  # pragma: no cover - defensive
        tool_calls = [tool_calls]
    normalized: list[dict[str, Any]] = []
    for idx, call in enumerate(tool_calls):
        if isinstance(call, LLMToolCall):
            call_id = call.id or f"tool_call_{idx}"
            name = call.name
            arguments: Any = call.arguments
        elif isinstance(call, Mapping):
            call_id = call.get("id") or call.get("tool_call_id") or call.get("call_id")
            function = call.get("function")
            if isinstance(function, Mapping):
                name = function.get("name")
                arguments = function.get("arguments")
            else:
                name = call.get("name")
                arguments = call.get("arguments")
        else:  # pragma: no cover - defensive for duck typing
            call_id = getattr(call, "id", None)
            function = getattr(call, "function", None)
            if function is not None:
                name = getattr(function, "name", None)
                arguments = getattr(function, "arguments", None)
            else:
                name = getattr(call, "name", None)
                arguments = getattr(call, "arguments", None)
            if call_id is None:
                call_id = getattr(call, "call_id", None)
        if not name:
            continue
        if call_id is None:
            call_id = f"tool_call_{idx}"
        arguments_str = _stringify_tool_arguments(arguments)
        normalized.append(
            {
                "id": str(call_id),
                "type": "function",
                "function": {
                    "name": str(name),
                    "arguments": arguments_str,
                },
            }
        )
    return normalized


class LLMResponseParser:
    """Convert raw LLM payloads into internal response structures."""

    def __init__(self, settings: "LLMSettings", message_format: str) -> None:
        from ..settings import LLMSettings  # local import to avoid cycles

        if not isinstance(settings, LLMSettings):  # pragma: no cover - defensive
            raise TypeError("settings must be an instance of LLMSettings")
        self.settings = settings
        self._message_format = message_format

    # ------------------------------------------------------------------
    def format_invalid_completion_error(self, prefix: str, completion: Any) -> str:
        summary = self._summarize_completion_payload(completion)
        hint = (
            "Verify that the configured base URL "
            f"{self.settings.base_url!r} exposes an OpenAI-compatible chat "
            "completions endpoint. If you are using LM Studio, ensure the URL "
            "ends with '/v1' (for example 'http://127.0.0.1:1234/v1')."
        )

        def _normalize(text: str) -> str:
            return text.rstrip(".")

        parts = [_normalize(prefix)]
        if summary:
            parts.append(_normalize(summary))
        parts.append(_normalize(hint))
        message = ". ".join(parts)
        if not message.endswith("."):
            message += "."
        return message

    def _summarize_completion_payload(self, completion: Any) -> str:
        def _clip(text: str, limit: int = 120) -> str:
            snippet = str(text).strip()
            if len(snippet) <= limit:
                return snippet
            return snippet[: limit - 3] + "..."

        summary_parts: list[str] = []
        mapping = extract_mapping(completion)
        if mapping is not None:
            keys = ", ".join(sorted(str(key) for key in mapping)) or "(none)"
            summary = (
                f"Response payload type {type(completion).__name__} "
                f"with keys: {keys}"
            )
            details: list[str] = []
            error_info = mapping.get("error")
            if isinstance(error_info, Mapping):
                message = error_info.get("message") or error_info.get("detail")
                code = error_info.get("code") or error_info.get("type")
                if message:
                    details.append(_clip(message))
                if code:
                    details.append(str(code))
            elif error_info:
                details.append(_clip(error_info))
            detail_value = mapping.get("detail")
            if detail_value:
                details.append(_clip(detail_value))
            if details:
                summary += f" ({'; '.join(details)})"
            summary_parts.append(summary)
        elif isinstance(completion, str):
            summary_parts.append(f"Response payload was a string: {_clip(completion)}")
        elif completion is None:
            summary_parts.append("Response payload was empty (None)")
        else:
            summary_parts.append(
                "Response payload type "
                f"{type(completion).__name__} is not OpenAI ChatCompletion-compatible"
            )

        response_obj = getattr(completion, "response", None)
        status_code = getattr(response_obj, "status_code", None)
        if status_code is not None:
            summary_parts.append(f"HTTP status {status_code}")
        return "; ".join(summary_parts)

    # ------------------------------------------------------------------
    def consume_stream(
        self,
        stream: Iterable[Any],
        *,
        cancellation: CancellationEvent | None,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, str]]]:
        message_parts: list[str] = []
        tool_chunks: dict[tuple[int, int], dict[str, Any]] = {}
        order: list[tuple[int, int]] = []
        closer = getattr(stream, "close", None)
        cancel_event = cancellation
        closed_by_cancel = False
        reasoning_segments: list[dict[str, str]] = []
        final_messages: dict[int, str] = {}
        chunk_level_fallback: str | None = None

        def ensure_not_cancelled() -> None:
            nonlocal closed_by_cancel
            if cancel_event is None:
                return
            if cancel_event.wait(timeout=0) or cancel_event.is_set():
                if callable(closer) and not closed_by_cancel:
                    closed_by_cancel = True
                    with suppress(Exception):  # pragma: no cover - defensive
                        closer()
                raise OperationCancelledError()

        from contextlib import suppress

        stream_error: Exception | None = None
        try:
            ensure_not_cancelled()
            for chunk in stream:  # pragma: no cover - network/streaming
                ensure_not_cancelled()
                chunk_map = extract_mapping(chunk)
                choices = getattr(chunk, "choices", None)
                if choices is None and chunk_map is not None:
                    choices = chunk_map.get("choices")
                if not choices:
                    if chunk_map is not None:
                        assistant_value = chunk_map.get("assistant")
                        if isinstance(assistant_value, str):
                            chunk_level_fallback = assistant_value
                    continue
                for choice in choices:
                    choice_map = extract_mapping(choice)
                    raw_choice_index = getattr(choice, "index", None)
                    if choice_map is not None and raw_choice_index is None:
                        raw_choice_index = choice_map.get("index")
                    choice_index = int(raw_choice_index or 0)
                    delta = getattr(choice, "delta", None)
                    if delta is None and choice_map is not None:
                        delta = choice_map.get("delta")
                    delta_map = extract_mapping(delta)
                    if delta_map is None:
                        delta_map = {}
                    reasoning = delta_map.get("reasoning") or delta_map.get("reasoning_content")
                    if reasoning:
                        fragments = collect_reasoning_fragments(reasoning)
                        self._append_reasoning_fragments(reasoning_segments, fragments)
                        tool_payloads = self._extract_reasoning_tool_calls(reasoning)
                        for payload in tool_payloads:
                            self._append_stream_tool_call(
                                tool_chunks,
                                order,
                                payload,
                                choice_index=choice_index,
                            )
                    if "content" in delta_map:
                        content_delta = delta_map["content"]
                    else:
                        content_delta = getattr(delta, "content", None)
                    if content_delta:
                        text_fragment = self._collect_text_segments(
                            content_delta,
                            reasoning_accumulator=None,
                            tool_payload_sink=None,
                        )
                        if text_fragment:
                            message_parts.append(text_fragment)
                    tool_calls = delta_map.get("tool_calls")
                    if tool_calls:
                        for idx, tool_call in enumerate(tool_calls):
                            self._append_stream_tool_call(
                                tool_chunks,
                                order,
                                tool_call,
                                choice_index=choice_index,
                                tool_index=idx,
                            )
                    function_call = delta_map.get("function_call")
                    if function_call:
                        self._append_stream_function_call(
                            tool_chunks,
                            order,
                            function_call,
                            choice_index=choice_index,
                        )
                    if choice_map is not None:
                        message_value = choice_map.get("message")
                        if message_value is not None:
                            temp_tool_payloads: list[Any] = []
                            message_text = self._extract_message_text(
                                message_value,
                                reasoning_accumulator=reasoning_segments,
                                tool_payload_sink=temp_tool_payloads,
                            )
                            if message_text:
                                final_messages[choice_index] = message_text
                            for idx, payload in enumerate(temp_tool_payloads):
                                self._append_stream_tool_call(
                                    tool_chunks,
                                    order,
                                    payload,
                                    choice_index=choice_index,
                                    tool_index=idx,
                                )
                        assistant_value = choice_map.get("assistant")
                        if isinstance(assistant_value, str):
                            chunk_level_fallback = assistant_value
            ensure_not_cancelled()
        except Exception as exc:
            if cancel_event is not None and (
                cancel_event.wait(timeout=0) or cancel_event.is_set()
            ):
                raise OperationCancelledError() from exc
            stream_error = exc
        finally:
            if callable(closer):
                with suppress(Exception):  # pragma: no cover - defensive
                    closer()
        message = "".join(message_parts)
        if not message and final_messages:
            message = final_messages.get(0) or next(iter(final_messages.values()))
        if not message and chunk_level_fallback:
            message = chunk_level_fallback
        tool_calls = [tool_chunks[key] for key in order if tool_chunks[key]["function"]["name"]]
        if stream_error is not None:
            log_debug_payload(
                "llm.response_parser.stream_interrupted",
                {
                    "error": {
                        "type": type(stream_error).__name__,
                        "message": str(stream_error),
                    },
                    "message_preview": message[:160],
                    "tool_calls": len(tool_calls),
                },
            )
        return message, tool_calls, reasoning_segments

    # ------------------------------------------------------------------
    def parse_chat_completion(
        self,
        completion: Any,
    ) -> tuple[str, list[dict[str, Any]], list[dict[str, str]]]:
        choices = getattr(completion, "choices", None)
        if not choices:
            raise ToolValidationError(
                self.format_invalid_completion_error(
                    "LLM response did not include any choices",
                    completion,
                )
            )
        message = getattr(choices[0], "message", None)
        if message is None:
            raise ToolValidationError(
                self.format_invalid_completion_error(
                    "LLM response did not include an assistant message",
                    completion,
                )
            )
        message_map = extract_mapping(message)
        attribute_tool_calls = getattr(message, "tool_calls", None) or []
        raw_tool_calls_payload: list[Any] = (
            [attribute_tool_calls]
            if isinstance(attribute_tool_calls, Mapping)
            else list(attribute_tool_calls)
        )
        reasoning_accumulator: list[dict[str, str]] = []
        message_text = self._extract_message_text(
            message,
            reasoning_accumulator=reasoning_accumulator,
            tool_payload_sink=raw_tool_calls_payload,
        )
        if not message_text and message_map is not None:
            direct_message = message_map.get("message")
            if isinstance(direct_message, str):
                message_text = direct_message
        if not message_text:
            completion_map = extract_mapping(completion)
            completion_assistant = getattr(completion, "assistant", None)
            if completion_assistant is None and completion_map is not None:
                completion_assistant = completion_map.get("assistant")
            if isinstance(completion_assistant, str):
                message_text = completion_assistant
        return message_text, raw_tool_calls_payload, reasoning_accumulator

    # ------------------------------------------------------------------
    def _extract_message_text(
        self,
        message: Any,
        *,
        reasoning_accumulator: list[dict[str, str]] | None = None,
        tool_payload_sink: list[Any] | None = None,
    ) -> str:
        if isinstance(message, str):
            return message
        message_map = extract_mapping(message)
        if message_map is None:
            return str(message or "")

        reasoning_payload = (
            message_map.get("reasoning_content")
            or message_map.get("reasoning")
        )
        if reasoning_payload and reasoning_accumulator is not None:
            fragments = collect_reasoning_fragments(reasoning_payload)
            if fragments:
                self._append_reasoning_fragments(reasoning_accumulator, fragments)
            if tool_payload_sink is not None:
                tool_payload_sink.extend(
                    self._extract_reasoning_tool_calls(reasoning_payload)
                )
        details_payload = message_map.get("reasoning_details")
        if details_payload and reasoning_accumulator is not None:
            fragments = collect_reasoning_fragments(details_payload)
            if fragments:
                self._append_reasoning_fragments(reasoning_accumulator, fragments)

        content = message_map.get("content")
        if content is None:
            content = getattr(message, "content", None)
        text = self._collect_text_segments(
            content,
            reasoning_accumulator=reasoning_accumulator,
            tool_payload_sink=tool_payload_sink,
        )

        tool_calls_payload = message_map.get("tool_calls")
        if (
            tool_calls_payload
            and tool_payload_sink is not None
            and not tool_payload_sink
        ):
            if isinstance(tool_calls_payload, Mapping):
                tool_payload_sink.append(tool_calls_payload)
            else:
                tool_payload_sink.extend(tool_calls_payload)

        if not text:
            for key in ("assistant", "text", "value", "output_text"):
                if key not in message_map:
                    continue
                fallback_text = self._collect_text_segments(
                    message_map.get(key),
                    reasoning_accumulator=None,
                    tool_payload_sink=None,
                )
                if fallback_text:
                    text = fallback_text
                    break
        return text

    def _collect_text_segments(
        self,
        content: Any,
        *,
        reasoning_accumulator: list[dict[str, str]] | None,
        tool_payload_sink: list[Any] | None,
    ) -> str:
        if not content:
            return ""
        if isinstance(content, str):
            return self._strip_think_blocks(
                content, reasoning_accumulator=reasoning_accumulator
            )
        if isinstance(content, Sequence) and not isinstance(content, (bytes, bytearray)):
            parts: list[str] = []
            for element in content:
                mapping = extract_mapping(element)
                if mapping is None:
                    if isinstance(element, str):
                        parts.append(element)
                    continue
                seg_type = mapping.get("type")
                if (
                    reasoning_accumulator is not None
                    and isinstance(seg_type, str)
                    and is_reasoning_type(seg_type)
                ):
                    fragments = collect_reasoning_fragments(mapping)
                    if fragments:
                        self._append_reasoning_fragments(
                            reasoning_accumulator, fragments
                        )
                    if tool_payload_sink is not None:
                        tool_payload_sink.extend(
                            self._extract_reasoning_tool_calls(mapping)
                        )
                    continue
                if (
                    seg_type == "text"
                    or (
                        isinstance(seg_type, str)
                        and seg_type.endswith("_text")
                    )
                ):
                    text_value = mapping.get("text")
                    if text_value:
                        parts.append(str(text_value))
                    continue
                text_value = mapping.get("text")
                if text_value and seg_type in {None, "message"}:
                    parts.append(str(text_value))
                    continue
                nested_content = mapping.get("content")
                if nested_content:
                    nested_text = self._collect_text_segments(
                        nested_content,
                        reasoning_accumulator=reasoning_accumulator,
                        tool_payload_sink=tool_payload_sink,
                    )
                    if nested_text:
                        parts.append(nested_text)
            return "".join(parts)
        if isinstance(content, Mapping):
            fragments = collect_reasoning_fragments(content)
            if fragments and reasoning_accumulator is not None:
                self._append_reasoning_fragments(reasoning_accumulator, fragments)
            if tool_payload_sink is not None:
                tool_payload_sink.extend(
                    self._extract_reasoning_tool_calls(content)
                )
            text_candidate = content.get("text") or content.get("content")
            if isinstance(text_candidate, (str, bytes, bytearray)):
                return str(text_candidate)
            return str(text_candidate or "")
        return str(content or "")

    _THINK_OPEN_RE = re.compile(r"<think(>|\s[^>]*>)", re.IGNORECASE)
    _THINK_CLOSE_RE = re.compile(r"</think>", re.IGNORECASE)

    def _strip_think_blocks(
        self,
        text: str,
        *,
        reasoning_accumulator: list[dict[str, str]] | None,
    ) -> str:
        if not text:
            return text
        lowered = text.lower()
        if "<think" not in lowered:
            return text

        parts: list[str] = []
        cursor = 0
        length = len(text)
        while True:
            open_match = self._THINK_OPEN_RE.search(text, cursor)
            if not open_match:
                break
            start = open_match.start()
            parts.append(text[cursor:start])
            tag_end = open_match.end()
            content_start = tag_end
            close_match = self._THINK_CLOSE_RE.search(text, tag_end)
            if close_match:
                content_end = close_match.start()
                cursor = close_match.end()
            else:
                content_end = length
                cursor = length
            inner = text[content_start:content_end]
            fragments = collect_reasoning_fragments(inner)
            if reasoning_accumulator is not None and fragments:
                normalized = [
                    ReasoningFragment(
                        type="reasoning",
                        text=fragment.text,
                        leading_whitespace=fragment.leading_whitespace,
                        trailing_whitespace=fragment.trailing_whitespace,
                    )
                    for fragment in fragments
                ]
                self._append_reasoning_fragments(reasoning_accumulator, normalized)
        if cursor < length:
            parts.append(text[cursor:])
        stripped = "".join(parts)
        if reasoning_accumulator is not None:
            residual_match = self._THINK_OPEN_RE.search(stripped)
            if residual_match:
                remainder = stripped[residual_match.end() :]
                fragments = collect_reasoning_fragments(remainder)
                if fragments:
                    normalized = [
                        ReasoningFragment(
                            type="reasoning",
                            text=fragment.text,
                            leading_whitespace=fragment.leading_whitespace,
                            trailing_whitespace=fragment.trailing_whitespace,
                        )
                        for fragment in fragments
                    ]
                    self._append_reasoning_fragments(
                        reasoning_accumulator, normalized
                    )
                stripped = stripped[: residual_match.start()]
        return stripped

    # ------------------------------------------------------------------
    def parse_harmony_output(
        self, completion: Any
    ) -> tuple[str, list[dict[str, Any]]]:
        output = getattr(completion, "output", None)
        if output is None:
            completion_map = extract_mapping(completion)
            if completion_map is not None:
                output = completion_map.get("output")
        if not output:
            raise ToolValidationError(
                self.format_invalid_completion_error(
                    "LLM response did not include any output blocks",
                    completion,
                )
            )
        message_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for item in output:
            item_map = extract_mapping(item)
            item_type = getattr(item, "type", None)
            if item_type is None and item_map is not None:
                item_type = item_map.get("type")
            if item_type == "message":
                content = getattr(item, "content", None)
                if content is None and item_map is not None:
                    content = item_map.get("content")
                for segment in content or []:
                    seg_map = extract_mapping(segment)
                    seg_type = getattr(segment, "type", None)
                    if seg_type is None and seg_map is not None:
                        seg_type = seg_map.get("type")
                    if seg_type in {"output_text", "text"}:
                        text_value = getattr(segment, "text", None)
                        if text_value is None and seg_map is not None:
                            text_value = seg_map.get("text")
                        if text_value:
                            message_parts.append(str(text_value))
            elif item_type == "function_call":
                item_map = item_map or {}
                name = getattr(item, "name", None) or item_map.get("name")
                arguments = (
                    getattr(item, "arguments", None) or item_map.get("arguments")
                )
                call_id = (
                    item_map.get("id")
                    or getattr(item, "id", None)
                    or item_map.get("call_id")
                    or getattr(item, "call_id", None)
                )
                tool_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": arguments},
                    }
                )
            elif item_type == "reasoning":
                continue
        return "".join(part for part in message_parts if part).strip(), tool_calls

    # ------------------------------------------------------------------
    def parse_tool_calls(self, tool_calls: Any) -> tuple[LLMToolCall, ...]:
        if not tool_calls:
            return ()

        iterable = [tool_calls] if isinstance(tool_calls, Mapping) else list(tool_calls)
        parsed: list[LLMToolCall] = []

        for idx, call in enumerate(iterable):
            if isinstance(call, LLMToolCall):
                parsed.append(call)
                continue

            call_map = extract_mapping(call)
            call_id = None
            function_payload: Any | None = None
            function_object: Any | None = None
            if call_map is not None:
                call_id = (
                    call_map.get("id")
                    or call_map.get("tool_call_id")
                    or call_map.get("call_id")
                )
                function_payload = call_map.get("function") or call_map.get("call")
            function_object = getattr(call, "function", None) or getattr(call, "call", None)
            if function_payload is None and function_object is not None:
                function_payload = function_object
            function_map = extract_mapping(function_payload)

            name = None
            if function_map is not None:
                name = function_map.get("name") or function_map.get("tool_name")
            if name is None and function_object is not None:
                name = getattr(function_object, "name", None)
            if name is None and call_map is not None:
                name = call_map.get("name")
            if name is None:
                name = getattr(call, "name", None)
            if not name:
                raise ToolValidationError(
                    "LLM response did not include a tool name",
                )

            if call_id is None:
                call_id = (
                    getattr(call, "id", None)
                    or getattr(call, "tool_call_id", None)
                    or getattr(call, "call_id", None)
                )
            if call_id is None and call_map is not None:
                call_id = call_map.get("call_id")
            if call_id is None:
                call_id = f"tool_call_{idx}"
            call_id_str = str(call_id)

            arguments_payload = None
            if function_map is not None and "arguments" in function_map:
                arguments_payload = function_map.get("arguments")
            if arguments_payload is None and function_object is not None:
                arguments_payload = getattr(function_object, "arguments", None)
            if arguments_payload is None and call_map is not None:
                arguments_payload = call_map.get("arguments")
            if arguments_payload is None:
                arguments_payload = getattr(call, "arguments", None)

            prepared_arguments = self._prepare_tool_arguments(
                arguments_payload,
                call_id=call_id_str,
                tool_name=str(name),
            )

            parsed.append(
                LLMToolCall(
                    id=call_id_str,
                    name=str(name),
                    arguments=prepared_arguments,
                )
            )

        return tuple(parsed)

    def _prepare_tool_arguments(
        self,
        payload: Any,
        *,
        call_id: str,
        tool_name: str,
    ) -> Mapping[str, Any]:
        mapping_candidate = None
        if isinstance(payload, Mapping):
            mapping_candidate = payload
        else:
            mapping_candidate = _extract_tool_argument_mapping(payload)
        if mapping_candidate is not None:
            safe_mapping = make_json_safe(
                mapping_candidate,
                stringify_keys=True,
                coerce_sequences=True,
                default=str,
            )
            if isinstance(safe_mapping, Mapping):
                return dict(safe_mapping)

        if isinstance(payload, bytes):
            text = payload.decode("utf-8", errors="replace")
        elif isinstance(payload, str):
            text = payload
        elif payload is None:
            text = "{}"
        else:
            text = _stringify_tool_arguments(payload)

        arguments = self._decode_tool_arguments(
            text or "{}",
            call_id=call_id,
            tool_name=tool_name,
        )
        if arguments is None or not isinstance(arguments, Mapping):
            raise ToolValidationError(
                "Tool arguments must be a JSON object",
            )
        safe_arguments = make_json_safe(
            arguments,
            stringify_keys=True,
            coerce_sequences=True,
            default=str,
        )
        if isinstance(safe_arguments, Mapping):
            return dict(safe_arguments)
        raise ToolValidationError(
            "Tool arguments must be a JSON object",
        )

    # ------------------------------------------------------------------
    def _extract_reasoning_tool_calls(self, payload: Any) -> list[dict[str, Any]]:
        entries = extract_reasoning_entries(payload)
        fragments: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for entry in entries:
            entry_type = str(entry.get("type") or "").lower()
            if entry_type not in {
                "tool_call",
                "tool_calls",
                "function_call",
                "tool_call_delta",
            } and not any(key in entry for key in ("tool_calls", "function")):
                continue
            tool_items: list[Mapping[str, Any]]
            raw_tool_calls = entry.get("tool_calls")
            if raw_tool_calls:
                if isinstance(raw_tool_calls, Mapping):
                    tool_items = [raw_tool_calls]
                else:
                    tool_items = [extract_mapping(elem) or {} for elem in raw_tool_calls]
            else:
                tool_items = [entry]
            for tool_entry in tool_items:
                if not tool_entry:
                    continue
                call_id = (
                    str(tool_entry.get("id"))
                    if tool_entry.get("id") is not None
                    else tool_entry.get("tool_call_id")
                )
                if not call_id:
                    call_id = str(len(order))
                if call_id not in fragments:
                    fragments[call_id] = {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": None, "arguments": ""},
                    }
                    order.append(call_id)
                fragment = fragments[call_id]
                function = tool_entry.get("function") or tool_entry.get("call") or {}
                if not isinstance(function, Mapping):
                    function = {}
                name = function.get("name") or tool_entry.get("name")
                if name:
                    fragment["function"]["name"] = str(name)
                args_fragment: Any = (
                    function.get("arguments")
                    if function.get("arguments") is not None
                    else tool_entry.get("arguments")
                )
                if args_fragment is None and "input" in tool_entry:
                    args_fragment = tool_entry.get("input")
                if args_fragment is None and "parameters" in tool_entry:
                    args_fragment = tool_entry.get("parameters")
                if args_fragment is None:
                    continue
                if isinstance(args_fragment, str):
                    fragment["function"]["arguments"] += args_fragment
                else:
                    try:
                        fragment["function"]["arguments"] += json.dumps(
                            args_fragment, ensure_ascii=False
                        )
                    except (TypeError, ValueError):
                        fragment["function"]["arguments"] += str(args_fragment)
        return [fragments[key] for key in order if fragments[key]["function"]["name"]]

    @staticmethod
    def _append_reasoning_fragments(
        aggregated: list[dict[str, Any]],
        fragments: Sequence[ReasoningFragment],
    ) -> None:
        for fragment in fragments:
            text = fragment.text
            if not text:
                continue
            seg_type = str(fragment.type or "reasoning")
            entry: dict[str, Any] = {"type": seg_type, "text": text}
            if fragment.leading_whitespace:
                entry["leading_whitespace"] = fragment.leading_whitespace
            if fragment.trailing_whitespace:
                entry["trailing_whitespace"] = fragment.trailing_whitespace
            aggregated.append(entry)

    def finalize_reasoning_segments(
        self, segments: Sequence[Mapping[str, Any]]
    ) -> tuple[LLMReasoningSegment, ...]:
        finalized: list[LLMReasoningSegment] = []
        seen: set[tuple[str, str, str, str]] = set()

        fragments = merge_reasoning_fragments(collect_reasoning_fragments(segments))
        for fragment in fragments:
            text_with_edges = (
                f"{fragment.leading_whitespace}{fragment.text}{fragment.trailing_whitespace}"
            )
            if not text_with_edges:
                continue
            stripped = fragment.text.strip()
            if not stripped:
                continue
            key = (
                fragment.type,
                stripped,
                fragment.leading_whitespace,
                fragment.trailing_whitespace,
            )
            if key in seen:
                continue
            seen.add(key)
            finalized.append(
                LLMReasoningSegment(
                    type=fragment.type,
                    text=stripped,
                    leading_whitespace=fragment.leading_whitespace,
                    trailing_whitespace=fragment.trailing_whitespace,
                )
            )
        return tuple(finalized)

    # ------------------------------------------------------------------
    def _append_stream_tool_call(
        self,
        tool_chunks: dict[tuple[int, int], dict[str, Any]],
        order: list[tuple[int, int]],
        tool_call: Any,
        *,
        choice_index: int,
        tool_index: int | None = None,
    ) -> None:
        call_map = extract_mapping(tool_call)
        key = (choice_index, tool_index or len(order))
        if key not in tool_chunks:
            tool_chunks[key] = {
                "id": None,
                "type": "function",
                "function": {"name": None, "arguments": ""},
            }
            order.append(key)
        entry = tool_chunks[key]
        call_id = getattr(tool_call, "id", None)
        if call_map is not None and call_id is None:
            call_id = (
                call_map.get("id")
                or call_map.get("tool_call_id")
                or call_map.get("call_id")
            )
        if call_id is None:
            call_id = getattr(tool_call, "call_id", None)
        if call_id:
            entry["id"] = call_id
        function = call_map.get("function") if call_map else None
        if function is None:
            function = getattr(tool_call, "function", None)
        if function is not None:
            func_map = extract_mapping(function)
        else:
            func_map = None
        name = getattr(function, "name", None)
        if func_map is not None and name is None:
            name = func_map.get("name")
        if name is None and call_map is not None:
            name = call_map.get("name")
        if name is None:
            name = getattr(tool_call, "name", None)
        if name:
            entry["function"]["name"] = name
        args_fragment = getattr(function, "arguments", None) if function else None
        if func_map is not None:
            args_fragment = func_map.get("arguments", args_fragment)
        if args_fragment is None and call_map is not None:
            args_fragment = call_map.get("arguments")
        if args_fragment is None:
            args_fragment = getattr(tool_call, "arguments", None)
        if args_fragment:
            entry["function"]["arguments"] += str(args_fragment)

    def _append_stream_function_call(
        self,
        tool_chunks: dict[tuple[int, int], dict[str, Any]],
        order: list[tuple[int, int]],
        function_call: Any,
        *,
        choice_index: int,
    ) -> None:
        func_map = extract_mapping(function_call)
        key = (choice_index, -1)
        if key not in tool_chunks:
            tool_chunks[key] = {
                "id": None,
                "type": "function",
                "function": {"name": None, "arguments": ""},
            }
            order.append(key)
        entry = tool_chunks[key]
        name = getattr(function_call, "name", None)
        if func_map is not None and name is None:
            name = func_map.get("name")
        if name:
            entry["function"]["name"] = name
        args_fragment = getattr(function_call, "arguments", None)
        if func_map is not None:
            args_fragment = func_map.get("arguments", args_fragment)
        if args_fragment:
            entry["function"]["arguments"] += str(args_fragment)

    # ------------------------------------------------------------------
    def _decode_tool_arguments(
        self,
        arguments_text: str,
        *,
        call_id: str,
        tool_name: str,
    ) -> Any:
        text = arguments_text or "{}"
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            recovery = self._recover_tool_arguments(text)
            if recovery is not None:
                self._log_recovered_tool_arguments(
                    text,
                    call_id=call_id,
                    tool_name=tool_name,
                    error=exc,
                    recovery=recovery,
                )
                return recovery.arguments
            self._log_invalid_tool_arguments(
                text,
                call_id=call_id,
                tool_name=tool_name,
                error=exc,
            )
            raise ToolValidationError(
                "LLM returned invalid JSON for tool arguments",
            ) from exc

    def _recover_tool_arguments(self, arguments_text: str) -> _ToolArgumentRecovery | None:
        stripped = (arguments_text or "").strip()
        if not stripped:
            return None
        decoder = json.JSONDecoder()
        fragments: list[Any] = []
        idx = 0
        length = len(stripped)
        while idx < length:
            char = stripped[idx]
            if char.isspace():
                idx += 1
                continue
            if char not in "{[":
                return None
            try:
                fragment, end = decoder.raw_decode(stripped, idx)
            except json.JSONDecodeError:
                return None
            fragments.append(fragment)
            idx = end
        if idx != length or len(fragments) <= 1:
            return None
        mapping_fragments: list[tuple[int, Mapping[str, Any]]] = [
            (index, fragment)
            for index, fragment in enumerate(fragments)
            if isinstance(fragment, Mapping)
        ]
        if not mapping_fragments:
            return None
        empty_mappings = sum(
            1
            for fragment in mapping_fragments
            if not fragment[1]
        )
        combined: dict[str, Any] = {}
        last_contributing_index = 0
        for index, fragment in mapping_fragments:
            if fragment:
                last_contributing_index = index
            for key, value in fragment.items():
                combined[key] = value
        if not combined:
            return None
        return _ToolArgumentRecovery(
            arguments=combined,
            classification="concatenated_json",
            fragments=len(fragments),
            recovered_fragment_index=last_contributing_index,
            empty_fragment_count=empty_mappings,
        )

    def _log_invalid_tool_arguments(
        self,
        arguments_text: str,
        *,
        call_id: str,
        tool_name: str,
        error: json.JSONDecodeError,
    ) -> None:
        text = arguments_text or ""
        preview, stripped = self._arguments_preview(text)
        classification: str | None = None
        if stripped:
            if "}{" in stripped or stripped.count("{") > 1:
                classification = "concatenated_json"
            elif stripped[0] not in "{[" and stripped[-1:] in "]}":
                classification = "trailing_garbage"
        payload = {
            "call_id": call_id,
            "tool_name": tool_name,
            "length": len(text),
            "classification": classification,
            "preview": preview,
            "error": {"type": type(error).__name__, "message": str(error)},
        }
        log_event("LLM_TOOL_ARGUMENTS_INVALID", payload)
        log_debug_payload(
            "LLM_TOOL_ARGUMENTS_INVALID",
            {
                **payload,
                "arguments_text": text,
                "lineno": error.lineno,
                "colno": error.colno,
                "pos": error.pos,
            },
        )

    def _log_recovered_tool_arguments(
        self,
        arguments_text: str,
        *,
        call_id: str,
        tool_name: str,
        error: json.JSONDecodeError,
        recovery: _ToolArgumentRecovery,
    ) -> None:
        text = arguments_text or ""
        preview, _ = self._arguments_preview(text)
        error_info = {
            "type": type(error).__name__,
            "message": str(error),
        }
        payload: dict[str, Any] = {
            "call_id": call_id,
            "tool_name": tool_name,
            "length": len(text),
            "classification": recovery.classification,
            "fragments": recovery.fragments,
            "recovered_fragment_index": recovery.recovered_fragment_index,
            "empty_fragments": recovery.empty_fragment_count,
            "preview": preview,
            "error": error_info,
        }
        if recovery.arguments:
            payload["recovered_keys"] = sorted(recovery.arguments.keys())
        log_event("LLM_TOOL_ARGUMENTS_RECOVERED", payload)
        debug_error = {
            **error_info,
            "lineno": error.lineno,
            "colno": error.colno,
            "pos": error.pos,
        }
        log_debug_payload(
            "LLM_TOOL_ARGUMENTS_RECOVERED",
            {
                **payload,
                "arguments_text": text,
                "recovered_arguments": dict(recovery.arguments),
                "error": debug_error,
            },
        )

    @staticmethod
    def _arguments_preview(
        arguments_text: str, *, limit: int = 200
    ) -> tuple[str, str]:
        text = arguments_text or ""
        stripped = text.strip()
        preview = (
            stripped[: limit - 3] + "..." if len(stripped) > limit else stripped
        )
        return preview, stripped
