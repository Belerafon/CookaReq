"""Client for interacting with an OpenAI-compatible LLM API."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Tuple, Mapping

import wx
from openai import OpenAI

from app.telemetry import log_event
from .spec import SYSTEM_PROMPT, TOOLS


@dataclass
class LLMSettings:
    """Settings for connecting to an LLM service."""

    api_base: str
    model: str
    api_key: str
    timeout: int

    @classmethod
    def from_config(cls, cfg: wx.Config) -> "LLMSettings":
        """Load settings from ``wx.Config`` instance."""
        return cls(
            api_base=cfg.Read("llm_api_base", ""),
            model=cfg.Read("llm_model", ""),
            api_key=cfg.Read("llm_api_key", ""),
            timeout=cfg.ReadInt("llm_timeout", 60),
        )


class LLMClient:
    """High-level client for LLM operations."""

    def __init__(self, cfg: wx.Config) -> None:
        self.settings = LLMSettings.from_config(cfg)
        self._client = OpenAI(
            base_url=self.settings.api_base or None,
            api_key=self.settings.api_key or None,
            timeout=self.settings.timeout,
        )

    # ------------------------------------------------------------------
    def check_llm(self) -> dict[str, Any]:
        """Perform a minimal request to verify connectivity."""
        payload = {
            "api_base": self.settings.api_base,
            "model": self.settings.model,
            "api_key": self.settings.api_key,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
        start = time.monotonic()
        log_event("LLM_REQUEST", payload)
        try:
            self._client.chat.completions.create(
                model=self.settings.model,
                messages=payload["messages"],
                max_tokens=payload["max_tokens"],
            )
        except Exception as exc:  # pragma: no cover - network errors
            log_event(
                "LLM_RESPONSE",
                {"error": {"type": type(exc).__name__, "message": str(exc)}},
                start_time=start,
            )
            return {"ok": False, "error": {"type": type(exc).__name__, "message": str(exc)}}
        log_event("LLM_RESPONSE", {"ok": True}, start_time=start)
        return {"ok": True}

    # ------------------------------------------------------------------
    def parse_command(self, text: str) -> Tuple[str, Mapping[str, Any]]:
        """Use the LLM to turn *text* into an MCP tool call.

        The model is instructed to choose exactly one of the predefined tools
        and provide JSON arguments for it via function calling.  Temperature is
        set to ``0`` to keep the output deterministic.
        """

        payload = {
            "api_base": self.settings.api_base,
            "model": self.settings.model,
            "api_key": self.settings.api_key,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "tools": TOOLS,
            "tool_choice": "required",
            "temperature": 0,
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
            )
            message = completion.choices[0].message
            tool_call = message.tool_calls[0]
            name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments or "{}")
            log_event("LLM_RESPONSE", {"tool": name, "arguments": arguments}, start_time=start)
            return name, arguments
        except Exception as exc:  # pragma: no cover - network errors
            log_event(
                "LLM_RESPONSE",
                {"error": {"type": type(exc).__name__, "message": str(exc)}},
                start_time=start,
            )
            raise
