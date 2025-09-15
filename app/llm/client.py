"""Client for interacting with an OpenAI-compatible LLM API."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

from ..settings import LLMSettings

# ``OpenAI`` импортируется динамически в конструкторе, чтобы тесты могли
# подменять ``openai.OpenAI`` до первого использования и тем самым избежать
# реальных сетевых запросов.
from ..telemetry import log_event
from .spec import SYSTEM_PROMPT, TOOLS

# When конфигурация не задаёт явное ограничение, используем консервативный
# дефолт, чтобы не отдавать бесконечно длинные ответы и не зависеть от
# серверных настроек.
DEFAULT_MAX_OUTPUT_TOKENS = 5000

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
    def parse_command(self, text: str) -> tuple[str, Mapping[str, Any]]:
        """Use the LLM to turn *text* into an MCP tool call.

        The model is instructed to choose exactly one of the predefined tools
        and provide JSON arguments for it via function calling.  Temperature is
        set to ``0`` to keep the output deterministic.
        """

        max_output_tokens = self._resolved_max_output_tokens()
        payload = {
            "base_url": self.settings.base_url,
            "model": self.settings.model,
            "api_key": self.settings.api_key,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
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
                messages=payload["messages"],
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
