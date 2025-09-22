"""Client for interacting with an OpenAI-compatible LLM API."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from ..settings import LLMSettings
from .constants import (
    DEFAULT_MAX_CONTEXT_TOKENS,
    MIN_MAX_CONTEXT_TOKENS,
)

# ``OpenAI`` импортируется динамически в конструкторе, чтобы тесты могли
# подменять ``openai.OpenAI`` до первого использования и тем самым избежать
# реальных сетевых запросов.
from ..telemetry import log_debug_payload, log_event
from ..util.cancellation import CancellationEvent, OperationCancelledError
from .spec import SYSTEM_PROMPT, TOOLS
from .tokenizer import count_text_tokens
from .validation import ToolValidationError, validate_tool_call


@dataclass(frozen=True, slots=True)
class LLMToolCall:
    """Structured representation of an MCP tool invocation."""

    id: str
    name: str
    arguments: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Assistant message possibly containing tool calls."""

    content: str
    tool_calls: tuple[LLMToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class HistoryTrimResult:
    """Container describing the outcome of history trimming."""

    kept_messages: list[dict[str, Any]]
    dropped_messages: int
    dropped_tokens: int
    total_messages: int
    total_tokens: int
    kept_tokens: int

# When the backend does not require authentication, the official OpenAI client
# still insists on a non-empty ``api_key``.  Using a harmless placeholder allows
# talking to such endpoints while making it explicit that no real key is
# configured.
NO_API_KEY = "sk-no-key"


class LLMClient:
    """High-level client for LLM operations."""

    def __init__(self, settings: LLMSettings) -> None:
        """Initialize client with LLM configuration ``settings``."""
        import openai

        self.settings = settings
        if not self.settings.base_url:
            raise ValueError("LLM base URL is not configured")
        api_key = self.settings.api_key or NO_API_KEY
        self._client = openai.OpenAI(
            base_url=self.settings.base_url,
            api_key=api_key,
            timeout=self.settings.timeout_minutes * 60,
            max_retries=self.settings.max_retries,
        )

    # ------------------------------------------------------------------
    def check_llm(self) -> dict[str, Any]:
        """Perform a minimal request to verify connectivity."""

        return self._check_llm()

    async def check_llm_async(self) -> dict[str, Any]:
        """Asynchronous counterpart to :meth:`check_llm`."""

        return await asyncio.to_thread(self._check_llm)

    # ------------------------------------------------------------------
    def parse_command(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        """Interpret *text* into an assistant reply with optional tool calls.

        The helper wraps :meth:`respond` by appending the user prompt to the
        provided *history* prior to dispatching the request.  Consumers that
        already manage the conversation can call :meth:`respond` directly.
        """

        conversation: list[Mapping[str, Any]] = list(history or [])
        conversation.append({"role": "user", "content": text})
        return self.respond(conversation, cancellation=cancellation)

    async def parse_command_async(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        """Asynchronous counterpart to :meth:`parse_command`."""

        conversation: list[Mapping[str, Any]] = list(history or [])
        conversation.append({"role": "user", "content": text})
        return await self.respond_async(
            conversation, cancellation=cancellation
        )

    # ------------------------------------------------------------------
    def respond(
        self,
        conversation: Sequence[Mapping[str, Any]] | None,
        *,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        """Send the full *conversation* to the model and return its reply."""

        return self._respond(
            list(conversation or []), cancellation=cancellation
        )

    async def respond_async(
        self,
        conversation: Sequence[Mapping[str, Any]] | None,
        *,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        """Asynchronous counterpart to :meth:`respond`."""

        return await asyncio.to_thread(
            self._respond,
            list(conversation or []),
            cancellation=cancellation,
        )

    def _format_invalid_completion_error(
        self, prefix: str, completion: Any
    ) -> str:
        """Return a detailed error message for unexpected completion payloads."""

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
        """Return a concise description of an unexpected completion payload."""

        def _clip(text: str, limit: int = 120) -> str:
            snippet = str(text).strip()
            if len(snippet) <= limit:
                return snippet
            return snippet[: limit - 3] + "..."

        summary_parts: list[str] = []
        mapping = self._extract_mapping(completion)
        if mapping is not None:
            keys = ", ".join(sorted(str(key) for key in mapping.keys())) or "(none)"
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

    @staticmethod
    def _extract_mapping(obj: Any) -> Mapping[str, Any] | None:
        """Return a mapping representation of *obj* when possible."""

        if isinstance(obj, Mapping):
            return obj
        for attr in ("model_dump", "dict"):
            method = getattr(obj, attr, None)
            if callable(method):
                try:
                    data = method()
                except Exception:  # pragma: no cover - defensive
                    continue
                if isinstance(data, Mapping):
                    return data
        data = getattr(obj, "_data", None)
        if isinstance(data, Mapping):
            return data
        return None

    # ------------------------------------------------------------------
    def _check_llm(self) -> dict[str, Any]:
        """Implementation shared by sync and async ``check_llm`` variants."""

        payload = {
            "base_url": self.settings.base_url,
            "model": self.settings.model,
            "api_key": self.settings.api_key,
            "messages": [{"role": "user", "content": "ping"}],
        }
        start = time.monotonic()
        log_debug_payload("LLM_REQUEST", {"direction": "outbound", **payload})
        log_event("LLM_REQUEST", payload)
        try:
            self._chat_completion(
                messages=payload["messages"],
            )
        except Exception as exc:  # pragma: no cover - network errors
            log_event(
                "LLM_RESPONSE",
                {"error": {"type": type(exc).__name__, "message": str(exc)}},
                start_time=start,
            )
            log_debug_payload(
                "LLM_RESPONSE",
                {
                    "direction": "inbound",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                },
            )
            return {
                "ok": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        log_event("LLM_RESPONSE", {"ok": True}, start_time=start)
        log_debug_payload(
            "LLM_RESPONSE",
            {"direction": "inbound", "ok": True},
        )
        return {"ok": True}

    # ------------------------------------------------------------------
    def _respond(
        self,
        conversation: Sequence[Mapping[str, Any]],
        *,
        cancellation: CancellationEvent | None = None,
    ) -> LLMResponse:
        """Implementation shared by sync and async response helpers."""

        messages = self._prepare_messages(conversation)
        use_stream = bool(cancellation) or self.settings.stream
        payload = {
            "base_url": self.settings.base_url,
            "model": self.settings.model,
            "api_key": self.settings.api_key,
            "messages": messages,
            "tools": TOOLS,
            "temperature": 0,
            "stream": use_stream,
        }
        start = time.monotonic()
        log_debug_payload("LLM_REQUEST", {"direction": "outbound", **payload})
        log_event("LLM_REQUEST", payload)

        try:
            completion = self._chat_completion(
                messages=messages,
                tools=payload["tools"],
                temperature=0,
                stream=use_stream,
            )
            if use_stream:
                message_text, raw_tool_calls = self._consume_stream(
                    completion, cancellation=cancellation
                )
                tool_calls = self._parse_tool_calls(raw_tool_calls)
            else:
                choices = getattr(completion, "choices", None)
                if not choices:
                    raise ToolValidationError(
                        self._format_invalid_completion_error(
                            "LLM response did not include any choices",
                            completion,
                        )
                    )
                message = getattr(choices[0], "message", None)
                if message is None:
                    raise ToolValidationError(
                        self._format_invalid_completion_error(
                            "LLM response did not include an assistant message",
                            completion,
                        )
                    )
                tool_calls = self._parse_tool_calls(
                    getattr(message, "tool_calls", None) or []
                )
                message_text = self._extract_message_content(
                    getattr(message, "content", None)
                ).strip()
            response = LLMResponse(
                content=message_text,
                tool_calls=tool_calls,
            )
            if not response.tool_calls and not response.content:
                raise ToolValidationError(
                    "LLM response did not include a tool call or message",
                )
        except OperationCancelledError:
            log_event(
                "LLM_RESPONSE",
                {"cancelled": True},
                start_time=start,
            )
            log_debug_payload(
                "LLM_RESPONSE",
                {"direction": "inbound", "cancelled": True},
            )
            raise
        except Exception as exc:  # pragma: no cover - network errors
            log_event(
                "LLM_RESPONSE",
                {"error": {"type": type(exc).__name__, "message": str(exc)}},
                start_time=start,
            )
            log_debug_payload(
                "LLM_RESPONSE",
                {
                    "direction": "inbound",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                },
            )
            raise
        else:
            log_payload: dict[str, Any] = {"message": response.content}
            if response.tool_calls:
                log_payload["tool_calls"] = [
                    {
                        "id": call.id,
                        "name": call.name,
                        "arguments": call.arguments,
                    }
                    for call in response.tool_calls
                ]
            log_event(
                "LLM_RESPONSE",
                log_payload,
                start_time=start,
            )
            log_debug_payload(
                "LLM_RESPONSE",
                {"direction": "inbound", **log_payload},
            )
            return LLMResponse(
                content=response.content.strip(),
                tool_calls=response.tool_calls,
            )

    def _consume_stream(
        self,
        stream: Iterable[Any],
        *,
        cancellation: CancellationEvent | None,
    ) -> tuple[str, list[dict[str, Any]]]:
        """Read streaming response and return message text with raw tool calls."""

        message_parts: list[str] = []
        tool_chunks: dict[tuple[int, int], dict[str, Any]] = {}
        order: list[tuple[int, int]] = []
        closer = getattr(stream, "close", None)
        cancel_event = cancellation
        closed_by_cancel = False

        def ensure_not_cancelled() -> None:
            nonlocal closed_by_cancel
            if cancel_event is None:
                return
            if cancel_event.wait(timeout=0) or cancel_event.is_set():
                if callable(closer) and not closed_by_cancel:
                    closed_by_cancel = True
                    try:
                        closer()
                    except Exception:  # pragma: no cover - defensive
                        pass
                raise OperationCancelledError()

        try:
            ensure_not_cancelled()
            for chunk in stream:  # pragma: no cover - network/streaming
                ensure_not_cancelled()
                chunk_map = self._extract_mapping(chunk)
                choices = getattr(chunk, "choices", None)
                if choices is None and chunk_map is not None:
                    choices = chunk_map.get("choices")
                if not choices:
                    continue
                for choice in choices:
                    choice_map = self._extract_mapping(choice)
                    raw_choice_index = getattr(choice, "index", None)
                    if choice_map is not None and raw_choice_index is None:
                        raw_choice_index = choice_map.get("index")
                    try:
                        choice_index = int(raw_choice_index)
                    except (TypeError, ValueError):
                        choice_index = 0
                    delta = getattr(choice, "delta", None)
                    if delta is None and choice_map is not None:
                        delta = choice_map.get("delta")
                    if delta is None:
                        continue
                    delta_map = self._extract_mapping(delta)
                    tool_calls_delta = getattr(delta, "tool_calls", None)
                    if tool_calls_delta is None and delta_map is not None:
                        tool_calls_delta = delta_map.get("tool_calls")
                    if tool_calls_delta:
                        self._append_stream_tool_calls(
                            tool_chunks,
                            order,
                            tool_calls_delta,
                            choice_index,
                        )
                    function_call = getattr(delta, "function_call", None)
                    if function_call is None and delta_map is not None:
                        function_call = delta_map.get("function_call")
                    if function_call:
                        self._append_stream_function_call(
                            tool_chunks,
                            order,
                            function_call,
                            choice_index,
                        )
                    content = getattr(delta, "content", None)
                    if content is None and delta_map is not None:
                        content = delta_map.get("content")
                    text = self._extract_message_content(content)
                    if text:
                        message_parts.append(text)
                if cancel_event is not None and cancel_event.is_set():
                    ensure_not_cancelled()
        except httpx.HTTPError as exc:  # pragma: no cover - network errors
            if cancel_event is not None and cancel_event.is_set():
                raise OperationCancelledError() from exc
            raise
        finally:
            if callable(closer) and not closed_by_cancel:
                try:
                    closer()
                except Exception:  # pragma: no cover - defensive
                    pass
        if cancel_event is not None and cancel_event.is_set():
            raise OperationCancelledError()
        raw_calls: list[dict[str, Any]] = []
        for key in order:
            data = tool_chunks.get(key)
            if not data:
                continue
            function = data.get("function", {})
            name = function.get("name")
            if not name:
                continue
            entry: dict[str, Any] = {
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": function.get("arguments") or "",
                },
            }
            call_id = data.get("id")
            if call_id:
                entry["id"] = call_id
            raw_calls.append(entry)
        return "".join(message_parts).strip(), raw_calls

    def _append_stream_tool_calls(
        self,
        tool_chunks: dict[tuple[int, int], dict[str, Any]],
        order: list[tuple[int, int]],
        tool_calls_delta: Any,
        choice_index: int,
    ) -> None:
        """Accumulate incremental tool call payloads from streaming chunks."""

        if isinstance(tool_calls_delta, Mapping):
            iterable = [tool_calls_delta]
        else:
            iterable = list(tool_calls_delta)
        for item in iterable:
            item_map = self._extract_mapping(item)
            raw_index = getattr(item, "index", None)
            if item_map is not None and raw_index is None:
                raw_index = item_map.get("index")
            try:
                tool_index = int(raw_index)
            except (TypeError, ValueError):
                tool_index = len(order)
            key = (choice_index, tool_index)
            if key not in tool_chunks:
                tool_chunks[key] = {
                    "id": None,
                    "type": "function",
                    "function": {"name": None, "arguments": ""},
                }
                order.append(key)
            entry = tool_chunks[key]
            call_id = getattr(item, "id", None) or getattr(item, "tool_call_id", None)
            if item_map is not None:
                call_id = item_map.get("id", call_id) or item_map.get(
                    "tool_call_id", call_id
                )
            if call_id:
                entry["id"] = call_id
            function = getattr(item, "function", None)
            if item_map is not None:
                function = item_map.get("function", function)
            if function is None:
                continue
            func_map = self._extract_mapping(function)
            name = getattr(function, "name", None)
            if func_map is not None and name is None:
                name = func_map.get("name")
            if name:
                entry["function"]["name"] = name
            args_fragment = getattr(function, "arguments", None)
            if func_map is not None:
                args_fragment = func_map.get("arguments", args_fragment)
            if args_fragment:
                entry["function"]["arguments"] += str(args_fragment)

    def _append_stream_function_call(
        self,
        tool_chunks: dict[tuple[int, int], dict[str, Any]],
        order: list[tuple[int, int]],
        function_call: Any,
        choice_index: int,
    ) -> None:
        """Normalize legacy ``function_call`` deltas during streaming."""

        func_map = self._extract_mapping(function_call)
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
    def _chat_completion(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        **kwargs: Any,
    ) -> Any:
        """Call the chat completions endpoint with normalized arguments."""

        base_kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
        }
        if kwargs:
            base_kwargs.update(kwargs)
        try:
            return self._client.chat.completions.create(**base_kwargs)
        except TypeError as exc:
            raise TypeError(
                "LLM client rejected provided arguments; "
                "verify that the backend is OpenAI-compatible."
            ) from exc

    def _resolved_max_context_tokens(self) -> int:
        """Return an explicit prompt context cap for requests."""

        limit = getattr(self.settings, "max_context_tokens", None)
        if limit is None or limit <= 0:
            return DEFAULT_MAX_CONTEXT_TOKENS
        if limit < MIN_MAX_CONTEXT_TOKENS:
            return MIN_MAX_CONTEXT_TOKENS
        return limit

    def _count_tokens(self, text: Any) -> int:
        """Return token usage for ``text`` using the configured model."""

        result = count_text_tokens(text, model=self.settings.model)
        return result.tokens or 0

    @staticmethod
    def _extract_message_content(content: Any) -> str:
        """Return textual payload from OpenAI chat message *content*."""

        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, Mapping):
            type_field = content.get("type")
            if type_field == "text":
                text_value = content.get("text")
                if isinstance(text_value, str):
                    return text_value
            text_value = content.get("text")
            if isinstance(text_value, str):
                return text_value
            return LLMClient._extract_message_content(content.get("content"))
        if isinstance(content, Sequence) and not isinstance(
            content, (str, bytes, bytearray)
        ):
            parts = [
                LLMClient._extract_message_content(part)
                for part in content
            ]
            return "".join(part for part in parts if part)
        type_attr = getattr(content, "type", None)
        if type_attr == "text":
            text_attr = getattr(content, "text", None)
            if isinstance(text_attr, str):
                return text_attr
        text_attr = getattr(content, "text", None)
        if isinstance(text_attr, str):
            return text_attr
        return LLMClient._extract_message_content(
            getattr(content, "content", None)
        )

    def _prepare_messages(
        self,
        conversation: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
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
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *trim_result.kept_messages,
        ]
        return messages

    def _sanitise_conversation(
        self,
        conversation: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        if not conversation:
            return []
        sanitized: list[dict[str, Any]] = []
        for message in conversation:
            role: str | None
            content: Any
            if isinstance(message, Mapping):
                role = message.get("role")  # type: ignore[assignment]
                content = message.get("content")
            else:  # pragma: no cover - defensive for duck typing
                role = getattr(message, "role", None)
                content = getattr(message, "content", None)
            if role is None:
                continue
            role_str = str(role)
            if role_str not in {"user", "assistant", "tool", "system"}:
                continue
            entry: dict[str, Any] = {
                "role": role_str,
                "content": "" if content is None else str(content),
            }
            if role_str == "assistant":
                tool_calls = (
                    message.get("tool_calls")  # type: ignore[assignment]
                    if isinstance(message, Mapping)
                    else getattr(message, "tool_calls", None)
                )
                normalized_calls = self._normalise_tool_calls(tool_calls)
                if normalized_calls:
                    entry["tool_calls"] = normalized_calls
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

    def _normalise_tool_calls(self, tool_calls: Any) -> list[dict[str, Any]]:
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

    def _parse_tool_calls(self, tool_calls: Any) -> tuple[LLMToolCall, ...]:
        if not tool_calls:
            return ()
        if isinstance(tool_calls, Mapping):  # pragma: no cover - defensive
            iterable = [tool_calls]
        else:
            iterable = list(tool_calls)
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
            try:
                arguments = json.loads(arguments_text or "{}")
            except json.JSONDecodeError as exc:
                raise ToolValidationError(
                    "LLM returned invalid JSON for tool arguments",
                ) from exc
            validated_arguments = validate_tool_call(name, arguments)
            parsed.append(
                LLMToolCall(id=str(call_id), name=name, arguments=validated_arguments)
            )
        return tuple(parsed)

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
        for index, message in enumerate(reversed(history)):
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
