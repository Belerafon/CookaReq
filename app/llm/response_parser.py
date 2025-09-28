"""Utilities for parsing LLM responses."""

from __future__ import annotations

import json
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

        try:
            ensure_not_cancelled()
            for chunk in stream:  # pragma: no cover - network/streaming
                ensure_not_cancelled()
                chunk_map = extract_mapping(chunk)
                choices = getattr(chunk, "choices", None)
                if choices is None and chunk_map is not None:
                    choices = chunk_map.get("choices")
                if not choices:
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
                        if isinstance(content_delta, list):
                            for item in content_delta:
                                segment = extract_mapping(item) or {}
                                if segment.get("type") == "text":
                                    text_value = segment.get("text") or ""
                                    message_parts.append(str(text_value))
                        else:
                            text_delta = getattr(content_delta, "text", None)
                            if text_delta is None and isinstance(content_delta, Mapping):
                                text_delta = content_delta.get("text")
                            if text_delta:
                                message_parts.append(str(text_delta))
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
            ensure_not_cancelled()
        finally:
            if callable(closer):
                with suppress(Exception):  # pragma: no cover - defensive
                    closer()
        message = "".join(message_parts)
        tool_calls = [tool_chunks[key] for key in order if tool_chunks[key]["function"]["name"]]
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
