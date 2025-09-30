"""Utilities for parsing LLM responses."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..telemetry import log_debug_payload, log_event
from ..util.cancellation import CancellationEvent, OperationCancelledError
from .reasoning import (
    collect_reasoning_fragments,
    extract_reasoning_entries,
    is_reasoning_type,
)
from .types import LLMReasoningSegment, LLMToolCall
from .utils import extract_mapping
from .validation import ToolValidationError, validate_tool_call

__all__ = [
    "LLMResponseParser",
    "StreamConsumptionError",
    "normalise_tool_calls",
]


class StreamConsumptionError(RuntimeError):
    """Signal that streaming aborted after partial output was received."""

    __slots__ = ("message_text", "raw_tool_calls_payload", "reasoning_segments")

    def __init__(
        self,
        message_text: str,
        raw_tool_calls_payload: list[dict[str, Any]],
        reasoning_segments: list[dict[str, str]],
    ) -> None:
        super().__init__("LLM stream ended prematurely")
        self.message_text = message_text
        self.raw_tool_calls_payload = raw_tool_calls_payload
        self.reasoning_segments = reasoning_segments


@dataclass(frozen=True, slots=True)
class _ToolArgumentRecovery:
    """Describe a successful recovery from a malformed tool argument payload."""

    arguments: Mapping[str, Any]
    classification: str
    fragments: int
    recovered_fragment_index: int
    empty_fragment_count: int


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
            call_id = call.get("id") or call.get("tool_call_id")
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
            name = getattr(function, "name", None) if function else None
            arguments = getattr(function, "arguments", None) if function else None
        if not name:
            continue
        if call_id is None:
            call_id = f"tool_call_{idx}"
        if isinstance(arguments, str):
            arguments_str = arguments
        else:
            try:
                arguments_str = json.dumps(arguments or {}, ensure_ascii=False)
            except (TypeError, ValueError):
                arguments_str = "{}"
        normalized.append(
            {
                "id": str(call_id),
                "type": "function",
                "function": {
                    "name": str(name),
                    "arguments": arguments_str or "{}",
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
    @staticmethod
    def _stringify_content(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, Mapping):
            for key in ("text", "content", "value", "assistant"):
                if key not in value:
                    continue
                text = LLMResponseParser._stringify_content(value.get(key))
                if text:
                    return text
            return ""
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            parts = [
                LLMResponseParser._stringify_content(item)
                for item in value
            ]
            return "".join(part for part in parts if part)
        return str(value)

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
        fallback_candidates: list[tuple[str, str]] = []
        fallback_samples: list[tuple[str, str]] = []
        fallback_primary: dict[str, str] | None = None
        fallback_secondary: list[dict[str, str]] | None = None
        recorded_chunks: list[dict[str, Any]] = []
        chunk_count = 0

        def _collect_candidate(label: str, value: Any) -> None:
            text = self._stringify_content(value)
            if not text:
                return
            fallback_samples.append((label, text))
            if text.strip():
                fallback_candidates.append((label, text))

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

        def _finalize_message() -> str:
            nonlocal fallback_primary, fallback_secondary
            message = "".join(message_parts)
            if message:
                return message
            if fallback_candidates:
                source, text = fallback_candidates[0]
                fallback_primary = {
                    "source": source,
                    "preview": text.strip()[:160],
                }
                return text
            if fallback_samples:
                fallback_secondary = [
                    {"source": source, "preview": sample.strip()[:160]}
                    for source, sample in fallback_samples
                ]
            return ""

        try:
            ensure_not_cancelled()
            for chunk in stream:  # pragma: no cover - network/streaming
                chunk_count += 1
                ensure_not_cancelled()
                chunk_map = extract_mapping(chunk)
                choices = getattr(chunk, "choices", None)
                if choices is None and chunk_map is not None:
                    choices = chunk_map.get("choices")
                if not choices:
                    if (
                        chunk_map is not None
                        and len(recorded_chunks) < 8
                    ):
                        recorded_chunks.append(
                            self._summarize_stream_chunk(
                                chunk_map, index=chunk_count
                            )
                        )
                    continue
                if chunk_map is not None and len(recorded_chunks) < 8:
                    recorded_chunks.append(
                        self._summarize_stream_chunk(
                            chunk_map, index=chunk_count
                        )
                    )
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
                        if isinstance(content_delta, list):
                            for item in content_delta:
                                segment = extract_mapping(item)
                                if segment is None:
                                    if isinstance(item, str):
                                        message_parts.append(str(item))
                                    continue
                                seg_type = segment.get("type")
                                if isinstance(seg_type, str) and is_reasoning_type(seg_type):
                                    fragments = collect_reasoning_fragments(segment)
                                    if fragments:
                                        self._append_reasoning_fragments(
                                            reasoning_segments, fragments
                                        )
                                    tool_fragments = self._extract_reasoning_tool_calls(
                                        segment
                                    )
                                    for payload in tool_fragments:
                                        self._append_stream_tool_call(
                                            tool_chunks,
                                            order,
                                            payload,
                                            choice_index=choice_index,
                                        )
                                    continue
                                if seg_type == "text" or (
                                    isinstance(seg_type, str)
                                    and seg_type.endswith("_text")
                                ):
                                    text_value = segment.get("text")
                                    if text_value:
                                        message_parts.append(str(text_value))
                                    continue
                                text_value = segment.get("text")
                                if text_value and seg_type in {None, "message"}:
                                    message_parts.append(str(text_value))
                                    continue
                                if text_value and seg_type not in {
                                    "tool_calls",
                                    "tool_call",
                                    "function_call",
                                }:
                                    message_parts.append(str(text_value))
                                    continue
                                nested_content = segment.get("content")
                                if nested_content:
                                    nested_text = self._stringify_content(
                                        nested_content
                                    )
                                    if nested_text:
                                        message_parts.append(nested_text)
                                    continue
                        else:
                            if isinstance(content_delta, (str, bytes, bytearray)):
                                message_parts.append(str(content_delta))
                            else:
                                text_delta = getattr(content_delta, "text", None)
                                if text_delta is None and isinstance(
                                    content_delta, Mapping
                                ):
                                    text_delta = content_delta.get("text")
                                if text_delta:
                                    message_parts.append(str(text_delta))
                                else:
                                    fallback_text = self._stringify_content(
                                        content_delta
                                    )
                                    if fallback_text:
                                        message_parts.append(fallback_text)
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
                    message_value = None
                    if choice_map is not None:
                        message_value = choice_map.get("message")
                    if message_value is not None:
                        _collect_candidate("choices[0].message", message_value)
                        message_map = extract_mapping(message_value)
                        if message_map is not None:
                            for key in (
                                "text",
                                "assistant",
                                "output_text",
                                "value",
                                "content",
                            ):
                                if key in message_map:
                                    _collect_candidate(
                                        f"choices[0].message.{key}",
                                        message_map.get(key),
                                    )
                            message_tool_calls = message_map.get("tool_calls")
                            if message_tool_calls:
                                for tool_index, payload in enumerate(message_tool_calls):
                                    self._append_stream_tool_call(
                                        tool_chunks,
                                        order,
                                        payload,
                                        choice_index=choice_index,
                                        tool_index=tool_index,
                                    )
                            message_function_call = message_map.get("function_call")
                            if message_function_call:
                                self._append_stream_function_call(
                                    tool_chunks,
                                    order,
                                    message_function_call,
                                    choice_index=choice_index,
                                )
                    if choice_map is not None:
                        for key in ("text", "assistant", "content"):
                            if key in choice_map:
                                _collect_candidate(
                                    f"choices[0].{key}",
                                    choice_map.get(key),
                                )
                        choice_tool_calls = choice_map.get("tool_calls")
                        if choice_tool_calls:
                            for tool_index, payload in enumerate(choice_tool_calls):
                                self._append_stream_tool_call(
                                    tool_chunks,
                                    order,
                                    payload,
                                    choice_index=choice_index,
                                    tool_index=tool_index,
                                )
                        choice_function_call = choice_map.get("function_call")
                        if choice_function_call:
                            self._append_stream_function_call(
                                tool_chunks,
                                order,
                                choice_function_call,
                                choice_index=choice_index,
                            )
                if chunk_map is not None:
                    for key in ("message", "assistant", "content"):
                        if key in chunk_map:
                            _collect_candidate(
                                f"chunk.{key}",
                                chunk_map.get(key),
                            )
                    chunk_tool_calls = chunk_map.get("tool_calls")
                    if chunk_tool_calls:
                        for tool_index, payload in enumerate(chunk_tool_calls):
                            self._append_stream_tool_call(
                                tool_chunks,
                                order,
                                payload,
                                choice_index=0,
                                tool_index=tool_index,
                            )
                    chunk_function_call = chunk_map.get("function_call")
                    if chunk_function_call:
                        self._append_stream_function_call(
                            tool_chunks,
                            order,
                            chunk_function_call,
                            choice_index=0,
                        )
            ensure_not_cancelled()
        except Exception as exc:
            if cancel_event is not None and (
                cancel_event.wait(timeout=0) or cancel_event.is_set()
            ):
                raise OperationCancelledError() from exc
            message = _finalize_message()
            if fallback_primary is not None:
                log_debug_payload(
                    "llm.response_parser.stream_message_fallback",
                    fallback_primary,
                )
            elif fallback_secondary is not None:
                log_debug_payload(
                    "llm.response_parser.stream_empty_message_candidates",
                    fallback_secondary,
                )
            tool_calls = [
                tool_chunks[key]
                for key in order
                if tool_chunks[key]["function"]["name"]
            ]
            log_debug_payload(
                "llm.response_parser.stream_truncated",
                {
                    "error_type": type(exc).__name__,
                    "message_preview": message.strip()[:160],
                    "tool_calls": len(tool_calls),
                },
            )
            raise StreamConsumptionError(
                message,
                tool_calls,
                reasoning_segments,
            ) from exc
        finally:
            if callable(closer):
                with suppress(Exception):  # pragma: no cover - defensive
                    closer()
        message = _finalize_message()
        if not message:
            info_payload: dict[str, Any] = {
                "chunks_seen": chunk_count,
            }
            if recorded_chunks:
                previews = [
                    chunk.get("preview")
                    for chunk in recorded_chunks
                    if isinstance(chunk, Mapping)
                    and isinstance(chunk.get("preview"), str)
                ]
                if previews:
                    info_payload["chunk_previews"] = previews[:5]
            if reasoning_segments:
                info_payload["reasoning_fragments"] = len(reasoning_segments)
            if tool_chunks:
                info_payload["tool_chunks"] = len(tool_chunks)
            log_event(
                "LLM_STREAM_EMPTY_MESSAGE",
                info_payload,
                level=logging.INFO,
            )

            debug_payload: dict[str, Any] = {
                "chunks_seen": chunk_count,
                "recorded_chunks": recorded_chunks,
            }
            if fallback_primary is not None:
                debug_payload["fallback_primary"] = fallback_primary
            if fallback_secondary is not None:
                debug_payload["fallback_secondary"] = fallback_secondary
            if reasoning_segments:
                debug_payload["reasoning_fragments"] = len(reasoning_segments)
            if tool_chunks:
                debug_payload["tool_chunks"] = len(tool_chunks)
            log_debug_payload(
                "llm.response_parser.stream_empty_message_details",
                debug_payload,
            )
        if fallback_primary is not None:
            log_debug_payload(
                "llm.response_parser.stream_message_fallback",
                fallback_primary,
            )
        elif fallback_secondary is not None:
            log_debug_payload(
                "llm.response_parser.stream_empty_message_candidates",
                fallback_secondary,
            )
        tool_calls = [
            tool_chunks[key]
            for key in order
            if tool_chunks[key]["function"]["name"]
        ]
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
        first_choice = choices[0]
        choice_map = extract_mapping(first_choice)
        message = getattr(first_choice, "message", None)
        if message is None:
            raise ToolValidationError(
                self.format_invalid_completion_error(
                    "LLM response did not include an assistant message",
                    completion,
                )
            )
        reasoning_payload = getattr(message, "reasoning_content", None)
        message_map = extract_mapping(message)
        if reasoning_payload is None:
            reasoning_payload = getattr(message, "reasoning", None)
        if reasoning_payload is None and message_map is not None:
            reasoning_payload = (
                message_map.get("reasoning_content")
                or message_map.get("reasoning")
            )
        raw_tool_calls_payload: list[Any] = list(
            getattr(message, "tool_calls", None) or []
        )
        reasoning_accumulator: list[dict[str, str]] = []
        completion_debug: dict[str, Any] | None = None
        if reasoning_payload:
            raw_tool_calls_payload.extend(
                self._extract_reasoning_tool_calls(reasoning_payload)
            )
            self._append_reasoning_fragments(
                reasoning_accumulator,
                collect_reasoning_fragments(reasoning_payload),
            )
        if message_map is not None:
            details_payload = message_map.get("reasoning_details")
            if details_payload:
                self._append_reasoning_fragments(
                    reasoning_accumulator,
                    collect_reasoning_fragments(details_payload),
                )
        content = getattr(message, "content", None)
        if content is None and message_map is not None:
            content = message_map.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for segment in content:
                mapping = extract_mapping(segment)
                if not mapping:
                    continue
                seg_type = mapping.get("type")
                if isinstance(seg_type, str) and is_reasoning_type(seg_type):
                    fragments = collect_reasoning_fragments(mapping)
                    if fragments:
                        self._append_reasoning_fragments(reasoning_accumulator, fragments)
                    tool_fragments = self._extract_reasoning_tool_calls(mapping)
                    if tool_fragments:
                        raw_tool_calls_payload.extend(tool_fragments)
                    continue
                if seg_type == "text" or (
                    isinstance(seg_type, str) and seg_type.endswith("_text")
                ):
                    text_value = mapping.get("text")
                    if text_value:
                        parts.append(str(text_value))
                    continue
                text_value = mapping.get("text")
                if text_value and seg_type in {None, "message"}:
                    parts.append(str(text_value))
            message_text = "".join(parts)
        elif isinstance(content, Mapping):
            fragments = collect_reasoning_fragments(content)
            if fragments:
                self._append_reasoning_fragments(reasoning_accumulator, fragments)
            tool_fragments = self._extract_reasoning_tool_calls(content)
            if tool_fragments:
                raw_tool_calls_payload.extend(tool_fragments)
            text_candidate = content.get("text") or content.get("content")
            message_text = str(text_candidate or "")
        else:
            message_text = str(content or "")
        if not message_text:
            fallback_candidates: list[tuple[str, str]] = []
            fallback_samples: list[tuple[str, str]] = []

            def _collect_candidate(label: str, value: Any) -> None:
                text = self._stringify_content(value)
                if not text:
                    return
                fallback_samples.append((label, text))
                if text.strip():
                    fallback_candidates.append((label, text))

            if completion_debug is None:
                completion_debug = self._summarize_completion_choice(
                    choice_map or {},
                    message_map or {},
                )

            if isinstance(message, str):
                _collect_candidate("choices[0].message", message)
            else:
                _collect_candidate(
                    "choices[0].message.text", getattr(message, "text", None)
                )

            if message_map is not None:
                for key in ("text", "assistant", "output_text", "value", "content"):
                    if key in message_map:
                        _collect_candidate(
                            f"choices[0].message.{key}", message_map.get(key)
                        )

            if choice_map is not None:
                for key in ("text", "assistant"):
                    if key in choice_map:
                        _collect_candidate(f"choices[0].{key}", choice_map.get(key))
                message_value = choice_map.get("message")
                if isinstance(message_value, str):
                    _collect_candidate("choices[0].message", message_value)

            completion_map = extract_mapping(completion)
            if completion_map is not None:
                for key in ("assistant", "content"):
                    if key in completion_map:
                        _collect_candidate(
                            f"completion.{key}", completion_map.get(key)
                        )
                message_payload = completion_map.get("message")
                if isinstance(message_payload, str):
                    _collect_candidate("completion.message", message_payload)

            if fallback_candidates:
                source, text = fallback_candidates[0]
                message_text = text
                log_debug_payload(
                    "llm.response_parser.message_fallback",
                    {
                        "source": source,
                        "preview": text.strip()[:160],
                    },
                )
            elif fallback_samples:
                log_debug_payload(
                    "llm.response_parser.empty_message_candidates",
                    {
                        "candidates": [
                            {
                                "source": source,
                                "preview": sample.strip()[:160],
                            }
                            for source, sample in fallback_samples
                        ],
                    },
                )
            if completion_debug is None:
                completion_debug = self._summarize_completion_choice(
                    choice_map or {},
                    message_map or {},
                )
            log_debug_payload(
                "llm.response_parser.empty_message_details",
                completion_debug,
            )
        return message_text, raw_tool_calls_payload, reasoning_accumulator

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
            if isinstance(call, Mapping):
                call_id = call.get("id") or call.get("tool_call_id")
                function = call.get("function")
                if not isinstance(function, Mapping):
                    function = {}
                name = function.get("name")
                arguments_payload = function.get("arguments")
            else:  # pragma: no cover - defensive for duck typing
                call_id = getattr(call, "id", None)
                function = getattr(call, "function", None)
                name = getattr(function, "name", None) if function else None
                arguments_payload = (
                    getattr(function, "arguments", None) if function else None
                )
            if not name:
                raise ToolValidationError(
                    "LLM response did not include a tool name",
                )
            if call_id is None:
                call_id = f"tool_call_{idx}"
            if isinstance(arguments_payload, str):
                arguments_text = arguments_payload or "{}"
            else:
                try:
                    arguments_text = json.dumps(
                        arguments_payload or {}, ensure_ascii=False
                    )
                except (TypeError, ValueError) as exc:
                    raise ToolValidationError(
                        "LLM returned invalid JSON for tool arguments",
                    ) from exc
            call_id_str = str(call_id)
            arguments = self._decode_tool_arguments(
                arguments_text or "{}",
                call_id=call_id_str,
                tool_name=str(name),
            )
            validated_arguments = validate_tool_call(name, arguments)
            parsed.append(
                LLMToolCall(id=call_id_str, name=name, arguments=validated_arguments)
            )
        return tuple(parsed)

    # ------------------------------------------------------------------
    def _summarize_stream_chunk(
        self, chunk_map: Mapping[str, Any], *, index: int
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {"index": index}
        if chunk_map:
            summary["chunk_keys"] = sorted(str(key) for key in chunk_map)[:8]
        choices = chunk_map.get("choices") if chunk_map else None
        if isinstance(choices, Sequence) and not isinstance(
            choices, (str, bytes, bytearray)
        ):
            summary["choices"] = len(choices)
            first_choice_map = extract_mapping(choices[0]) if choices else None
            if first_choice_map:
                summary["choice_keys"] = sorted(str(key) for key in first_choice_map)[
                    :8
                ]
                delta = first_choice_map.get("delta")
                if delta is None:
                    delta = getattr(choices[0], "delta", None)
                delta_map = extract_mapping(delta)
                if delta_map:
                    summary["delta_keys"] = sorted(str(key) for key in delta_map)[:8]
                    preview = self._stringify_content(delta_map.get("content"))
                    if not preview:
                        preview = self._stringify_content(delta_map.get("message"))
                    if preview:
                        summary["preview"] = preview.strip()[:160]
                    tool_calls = delta_map.get("tool_calls")
                    if tool_calls:
                        if isinstance(tool_calls, Sequence) and not isinstance(
                            tool_calls, (str, bytes, bytearray)
                        ):
                            summary["tool_call_deltas"] = len(tool_calls)
                        else:
                            summary["tool_call_deltas"] = 1
                    if delta_map.get("function_call"):
                        summary["has_function_call_delta"] = True
            else:
                preview = self._stringify_content(choices[0]) if choices else ""
                if preview:
                    summary["preview"] = preview.strip()[:160]
        else:
            preview = self._stringify_content(
                chunk_map.get("message")
                if chunk_map
                else None
            )
            if not preview and chunk_map:
                preview = self._stringify_content(chunk_map.get("assistant"))
            if preview:
                summary["preview"] = preview.strip()[:160]
        return summary

    def _summarize_completion_choice(
        self,
        choice_map: Mapping[str, Any],
        message_map: Mapping[str, Any],
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        if choice_map:
            summary["choice_keys"] = sorted(str(key) for key in choice_map)[:8]
            raw_message = choice_map.get("message")
            if isinstance(raw_message, str):
                summary["message_str_preview"] = raw_message.strip()[:160]
        if message_map:
            summary["message_keys"] = sorted(str(key) for key in message_map)[:8]
            role = message_map.get("role")
            if role:
                summary["role"] = str(role)
            tool_calls = message_map.get("tool_calls")
            if tool_calls:
                if isinstance(tool_calls, Sequence) and not isinstance(
                    tool_calls, (str, bytes, bytearray)
                ):
                    summary["tool_calls"] = len(tool_calls)
                else:
                    summary["tool_calls"] = 1
            content = message_map.get("content")
            if content is not None:
                summary["content_type"] = type(content).__name__
                preview = self._stringify_content(content)
                if preview:
                    summary["content_preview"] = preview.strip()[:160]
            text_value = message_map.get("text")
            if isinstance(text_value, str) and text_value.strip():
                summary["text_preview"] = text_value.strip()[:160]
        return summary

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
        aggregated: list[dict[str, str]], fragments: Sequence[tuple[str, str]]
    ) -> None:
        for raw_type, raw_text in fragments:
            if not raw_text:
                continue
            text = str(raw_text)
            if not text:
                continue
            seg_type = str(raw_type or "reasoning")
            aggregated.append({"type": seg_type, "text": text})

    def finalize_reasoning_segments(
        self, segments: Sequence[Mapping[str, str]]
    ) -> tuple[LLMReasoningSegment, ...]:
        finalized: list[LLMReasoningSegment] = []
        for segment in segments:
            seg_type = str(segment.get("type") or "reasoning")
            text = str(segment.get("text") or "").strip()
            if not text:
                continue
            finalized.append(LLMReasoningSegment(type=seg_type, text=text))
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
        key_index = tool_index if tool_index is not None else len(order)
        key = (choice_index, key_index)
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
            call_id = call_map.get("id") or call_map.get("tool_call_id")
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
        if name:
            entry["function"]["name"] = name
        args_fragment = getattr(function, "arguments", None) if function else None
        if func_map is not None:
            args_fragment = func_map.get("arguments", args_fragment)
        self._merge_tool_arguments(entry["function"], args_fragment)

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
        self._merge_tool_arguments(entry["function"], args_fragment)

    @staticmethod
    def _merge_tool_arguments(target: dict[str, Any], fragment: Any) -> None:
        if fragment is None:
            return
        if isinstance(fragment, str):
            current = target.get("arguments")
            if isinstance(current, str):
                target["arguments"] = (current or "") + fragment
            elif current in (None, ""):
                target["arguments"] = fragment
            else:
                return
            return
        if isinstance(fragment, Mapping):
            incoming = dict(fragment)
            current = target.get("arguments")
            if isinstance(current, Mapping):
                merged = dict(current)
                merged.update(incoming)
            else:
                merged = incoming
            target["arguments"] = merged
            return
        if isinstance(fragment, Sequence) and not isinstance(
            fragment, (str, bytes, bytearray)
        ):
            incoming_list = list(fragment)
            current = target.get("arguments")
            if isinstance(current, Sequence) and not isinstance(
                current, (str, bytes, bytearray)
            ):
                target["arguments"] = list(current) + incoming_list
            else:
                target["arguments"] = incoming_list
            return
        current = target.get("arguments")
        if isinstance(current, str):
            target["arguments"] = current + str(fragment)
        elif current in (None, ""):
            target["arguments"] = str(fragment)

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
        selected_index: int | None = None
        selected_fragment: Mapping[str, Any] | None = None
        for index, fragment in reversed(mapping_fragments):
            if fragment:
                selected_index = index
                selected_fragment = fragment
                break
        if selected_fragment is None:
            selected_index, selected_fragment = mapping_fragments[-1]
        if selected_fragment is None:
            return None
        empty_mappings = sum(
            1
            for fragment in fragments
            if isinstance(fragment, Mapping) and not fragment
        )
        return _ToolArgumentRecovery(
            arguments=dict(selected_fragment),
            classification="concatenated_json",
            fragments=len(fragments),
            recovered_fragment_index=selected_index or 0,
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
