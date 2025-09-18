"""Client for interacting with an OpenAI-compatible LLM API."""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..settings import LLMSettings
from .constants import (
    DEFAULT_MAX_CONTEXT_TOKENS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    MIN_MAX_CONTEXT_TOKENS,
)

# ``OpenAI`` импортируется динамически в конструкторе, чтобы тесты могли
# подменять ``openai.OpenAI`` до первого использования и тем самым избежать
# реальных сетевых запросов.
from ..telemetry import log_debug_payload, log_event
from .spec import SYSTEM_PROMPT, TOOLS
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

# When the backend does not require authentication, the official OpenAI client
# still insists on a non-empty ``api_key``.  Using a harmless placeholder allows
# talking to such endpoints while making it explicit that no real key is
# configured.
NO_API_KEY = "sk-no-key"

TOKEN_PARAM_CANDIDATES: tuple[str, ...] = (
    "max_tokens",
    "max_completion_tokens",
    "max_output_tokens",
)


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
        self._token_param_candidates = self._detect_token_param_candidates()
        self._token_param_index = 0
        self._token_param_warning_emitted = False

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
    ) -> LLMResponse:
        """Interpret *text* into an assistant reply with optional tool calls.

        The helper wraps :meth:`respond` by appending the user prompt to the
        provided *history* prior to dispatching the request.  Consumers that
        already manage the conversation can call :meth:`respond` directly.
        """

        conversation: list[Mapping[str, Any]] = list(history or [])
        conversation.append({"role": "user", "content": text})
        return self.respond(conversation)

    async def parse_command_async(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
    ) -> LLMResponse:
        """Asynchronous counterpart to :meth:`parse_command`."""

        conversation: list[Mapping[str, Any]] = list(history or [])
        conversation.append({"role": "user", "content": text})
        return await self.respond_async(conversation)

    # ------------------------------------------------------------------
    def respond(
        self, conversation: Sequence[Mapping[str, Any]] | None
    ) -> LLMResponse:
        """Send the full *conversation* to the model and return its reply."""

        return self._respond(list(conversation or []))

    async def respond_async(
        self, conversation: Sequence[Mapping[str, Any]] | None
    ) -> LLMResponse:
        """Asynchronous counterpart to :meth:`respond`."""

        return await asyncio.to_thread(self._respond, list(conversation or []))

    # ------------------------------------------------------------------
    def _detect_token_param_candidates(self) -> list[str]:
        """Inspect client signature to determine supported token arguments."""

        create = self._client.chat.completions.create
        try:
            signature = inspect.signature(create)
        except (TypeError, ValueError):
            return list(TOKEN_PARAM_CANDIDATES)
        params = signature.parameters
        candidates = [
            name for name in TOKEN_PARAM_CANDIDATES if name in params
        ]
        if candidates:
            return candidates
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            return list(TOKEN_PARAM_CANDIDATES)
        return []

    def _current_token_param(self) -> str | None:
        """Return the currently selected token parameter name, if any."""

        if 0 <= self._token_param_index < len(self._token_param_candidates):
            return self._token_param_candidates[self._token_param_index]
        return None

    def _advance_token_param(self) -> None:
        """Switch to the next available token parameter option."""

        self._token_param_index += 1

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

        max_output_tokens = self._resolved_max_output_tokens()
        token_param = self._current_token_param()
        payload = {
            "base_url": self.settings.base_url,
            "model": self.settings.model,
            "api_key": self.settings.api_key,
            "messages": [{"role": "user", "content": "ping"}],
            # Respect configured limit; when пользователь ничего не указал,
            # применяем собственный консервативный дефолт, чтобы сервер не
            # приходилось угадывать ограничения.
            "max_output_tokens": max_output_tokens,
            "token_parameter": token_param,
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
        self, conversation: Sequence[Mapping[str, Any]]
    ) -> LLMResponse:
        """Implementation shared by sync and async response helpers."""

        max_output_tokens = self._resolved_max_output_tokens()
        token_param = self._current_token_param()
        messages = self._prepare_messages(conversation)
        payload = {
            "base_url": self.settings.base_url,
            "model": self.settings.model,
            "api_key": self.settings.api_key,
            "messages": messages,
            "tools": TOOLS,
            "temperature": 0,
            "max_output_tokens": max_output_tokens,
            "stream": self.settings.stream,
            "token_parameter": token_param,
        }
        start = time.monotonic()
        log_debug_payload("LLM_REQUEST", {"direction": "outbound", **payload})
        log_event("LLM_REQUEST", payload)

        try:
            completion = self._chat_completion(
                messages=messages,
                tools=payload["tools"],
                temperature=0,
                stream=self.settings.stream,
            )
            if self.settings.stream:
                message_parts: list[str] = []
                tool_chunks: dict[str, dict[str, str]] = {}
                tool_order: list[str] = []
                for chunk in completion:  # pragma: no cover - network/streaming
                    delta = chunk.choices[0].delta
                    tool_calls_delta = getattr(delta, "tool_calls", None)
                    if tool_calls_delta:
                        for tool_delta in tool_calls_delta:
                            call_id = (
                                getattr(tool_delta, "id", None)
                                or getattr(tool_delta, "tool_call_id", None)
                            )
                            if not call_id:
                                call_id = f"tool_call_{len(tool_order)}"
                            if call_id not in tool_chunks:
                                tool_chunks[call_id] = {"name": "", "arguments": ""}
                                tool_order.append(call_id)
                            fn = getattr(tool_delta, "function", None)
                            if fn is not None:
                                name = getattr(fn, "name", None)
                                if name:
                                    tool_chunks[call_id]["name"] = name
                                args_fragment = getattr(fn, "arguments", None)
                                if args_fragment:
                                    tool_chunks[call_id]["arguments"] += args_fragment
                    text = self._extract_message_content(
                        getattr(delta, "content", None)
                    )
                    if text:
                        message_parts.append(text)
                raw_calls: list[dict[str, Any]] = []
                for call_id in tool_order:
                    data = tool_chunks[call_id]
                    if not data["name"]:
                        continue
                    raw_calls.append(
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": data["name"],
                                "arguments": data["arguments"],
                            },
                        }
                    )
                tool_calls = self._parse_tool_calls(raw_calls)
                message_text = "".join(message_parts).strip()
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

    # ------------------------------------------------------------------
    def _chat_completion(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        **kwargs: Any,
    ) -> Any:
        """Call the chat completions endpoint honouring token limit settings."""

        token_limit = self._resolved_max_output_tokens()
        base_kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
        }
        if kwargs:
            base_kwargs.update(kwargs)

        while True:
            param = self._current_token_param()
            call_kwargs = dict(base_kwargs)
            if param:
                call_kwargs[param] = token_limit
            elif not self._token_param_warning_emitted:
                log_event(
                    "LLM_TOKEN_LIMIT_SKIPPED",
                    {
                        "reason": "no-supported-parameter",
                        "max_output_tokens": token_limit,
                    },
                )
                self._token_param_warning_emitted = True
            try:
                return self._client.chat.completions.create(**call_kwargs)
            except TypeError as exc:
                if param and self._is_unexpected_keyword_error(exc, param):
                    log_event(
                        "LLM_TOKEN_PARAM_UNSUPPORTED",
                        {"parameter": param, "message": str(exc)},
                    )
                    self._advance_token_param()
                    continue
                raise

    @staticmethod
    def _is_unexpected_keyword_error(exc: TypeError, param: str) -> bool:
        """Return ``True`` when *exc* signals an unsupported keyword argument."""

        text = str(exc)
        return "unexpected keyword" in text.lower() and param in text

    # ------------------------------------------------------------------
    def _resolved_max_output_tokens(self) -> int:
        """Return an explicit token cap for requests."""

        limit = self.settings.max_output_tokens
        if limit is None or limit <= 0:
            return DEFAULT_MAX_OUTPUT_TOKENS
        return limit

    def _resolved_max_context_tokens(self) -> int:
        """Return an explicit prompt context cap for requests."""

        limit = getattr(self.settings, "max_context_tokens", None)
        if limit is None or limit <= 0:
            return DEFAULT_MAX_CONTEXT_TOKENS
        if limit < MIN_MAX_CONTEXT_TOKENS:
            return MIN_MAX_CONTEXT_TOKENS
        return limit

    @staticmethod
    def _count_tokens(text: Any) -> int:
        """Very simple whitespace-based token counter."""

        if not text:
            return 0
        if not isinstance(text, str):
            text = str(text)
        return len(text.split())

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
        trimmed_history, dropped_messages, dropped_tokens = self._trim_history(
            sanitized_history,
            remaining_tokens=remaining,
        )
        if dropped_messages:
            log_event(
                "LLM_CONTEXT_TRIMMED",
                {
                    "dropped_messages": dropped_messages,
                    "dropped_tokens": dropped_tokens,
                },
            )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *trimmed_history,
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
            if role_str not in {"user", "assistant", "tool"}:
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
    ) -> tuple[list[dict[str, str]], int, int]:
        if not history:
            return [], 0, 0
        total_tokens = sum(self._count_tokens(msg["content"]) for msg in history)
        if remaining_tokens <= 0:
            return [], len(history), total_tokens

        kept_rev: list[dict[str, str]] = []
        kept_tokens = 0
        for index, message in enumerate(reversed(history)):
            tokens = self._count_tokens(message["content"])
            if tokens > remaining_tokens and kept_rev:
                break
            kept_rev.append(message)
            kept_tokens += tokens
            remaining_tokens = max(remaining_tokens - tokens, 0)
        kept = list(reversed(kept_rev))
        dropped_messages = len(history) - len(kept)
        dropped_tokens = total_tokens - kept_tokens
        return kept, dropped_messages, dropped_tokens
