"""Client for interacting with an OpenAI-compatible LLM API."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping, Sequence
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
from ..telemetry import log_event
from .spec import SYSTEM_PROMPT, TOOLS
from .validation import validate_tool_call

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
    ) -> tuple[str, Mapping[str, Any]]:
        """Use the LLM to turn *text* into an MCP tool call.

        The model is instructed to choose exactly one of the predefined tools
        and provide JSON arguments for it via function calling.  Temperature is
        set to ``0`` to keep the output deterministic.
        """

        return self._parse_command(text, history=history)

    async def parse_command_async(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
    ) -> tuple[str, Mapping[str, Any]]:
        """Asynchronous counterpart to :meth:`parse_command`."""

        return await asyncio.to_thread(self._parse_command, text, history=history)

    # ------------------------------------------------------------------
    def _check_llm(self) -> dict[str, Any]:
        """Implementation shared by sync and async ``check_llm`` variants."""

        max_output_tokens = self._resolved_max_output_tokens()
        payload = {
            "base_url": self.settings.base_url,
            "model": self.settings.model,
            "api_key": self.settings.api_key,
            "messages": [{"role": "user", "content": "ping"}],
            # Respect configured limit; when пользователь ничего не указал,
            # применяем собственный консервативный дефолт, чтобы сервер не
            # приходилось угадывать ограничения.
            "max_output_tokens": max_output_tokens,
        }
        start = time.monotonic()
        log_event("LLM_REQUEST", payload)
        try:
            self._client.chat.completions.create(
                model=self.settings.model,
                messages=payload["messages"],
                max_output_tokens=max_output_tokens,
            )
        except Exception as exc:  # pragma: no cover - network errors
            log_event(
                "LLM_RESPONSE",
                {"error": {"type": type(exc).__name__, "message": str(exc)}},
                start_time=start,
            )
            return {
                "ok": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        log_event("LLM_RESPONSE", {"ok": True}, start_time=start)
        return {"ok": True}

    # ------------------------------------------------------------------
    def _parse_command(
        self,
        text: str,
        *,
        history: Sequence[Mapping[str, Any]] | None = None,
    ) -> tuple[str, Mapping[str, Any]]:
        """Implementation shared by sync and async ``parse_command`` variants."""

        max_output_tokens = self._resolved_max_output_tokens()
        messages = self._build_messages(text, history)
        payload = {
            "base_url": self.settings.base_url,
            "model": self.settings.model,
            "api_key": self.settings.api_key,
            "messages": messages,
            "tools": TOOLS,
            "tool_choice": "required",
            "temperature": 0,
            "max_output_tokens": max_output_tokens,
            "stream": self.settings.stream,
        }
        start = time.monotonic()
        log_event("LLM_REQUEST", payload)

        try:
            completion = self._client.chat.completions.create(
                model=self.settings.model,
                messages=messages,
                tools=payload["tools"],
                tool_choice="required",
                temperature=0,
                max_output_tokens=max_output_tokens,
                stream=self.settings.stream,
            )
            if self.settings.stream:
                args_json = ""
                name = ""
                for chunk in completion:  # pragma: no cover - network/streaming
                    delta = chunk.choices[0].delta
                    tool_calls = getattr(delta, "tool_calls", None)
                    if tool_calls:
                        tc = tool_calls[0]
                        fn = getattr(tc, "function", None)
                        if fn:
                            name = getattr(fn, "name", name) or name
                            args_json += getattr(fn, "arguments", "") or ""
                arguments = json.loads(args_json or "{}")
            else:
                message = completion.choices[0].message
                tool_call = message.tool_calls[0]
                name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments or "{}")
            arguments = validate_tool_call(name, arguments)
        except Exception as exc:  # pragma: no cover - network errors
            log_event(
                "LLM_RESPONSE",
                {"error": {"type": type(exc).__name__, "message": str(exc)}},
                start_time=start,
            )
            raise
        else:
            log_event(
                "LLM_RESPONSE",
                {"tool": name, "arguments": arguments},
                start_time=start,
            )
            return name, arguments

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
    def _count_tokens(text: str) -> int:
        """Very simple whitespace-based token counter."""

        if not text:
            return 0
        return len(text.split())

    def _build_messages(
        self,
        text: str,
        history: Sequence[Mapping[str, Any]] | None,
    ) -> list[dict[str, str]]:
        sanitized_history = self._prepare_history(history)
        limit = self._resolved_max_context_tokens()
        reserved = self._count_tokens(SYSTEM_PROMPT) + self._count_tokens(text)
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
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *trimmed_history,
            {"role": "user", "content": text},
        ]
        return messages

    def _prepare_history(
        self,
        history: Sequence[Mapping[str, Any]] | None,
    ) -> list[dict[str, str]]:
        if not history:
            return []
        sanitized: list[dict[str, str]] = []
        for message in history:
            if isinstance(message, Mapping):
                role = message.get("role")
                content = message.get("content")
            else:  # pragma: no cover - defensive for duck typing
                role = getattr(message, "role", None)
                content = getattr(message, "content", None)
            if role not in {"user", "assistant"}:
                continue
            sanitized.append(
                {
                    "role": str(role),
                    "content": "" if content is None else str(content),
                }
            )
        return sanitized

    def _trim_history(
        self,
        history: list[dict[str, str]],
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
        for message in reversed(history):
            tokens = self._count_tokens(message["content"])
            if tokens > remaining_tokens:
                break
            kept_rev.append(message)
            kept_tokens += tokens
            remaining_tokens -= tokens
        kept = list(reversed(kept_rev))
        dropped_messages = len(history) - len(kept)
        dropped_tokens = total_tokens - kept_tokens
        return kept, dropped_messages, dropped_tokens
