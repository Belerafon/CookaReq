"""Client for interacting with an OpenAI-compatible LLM API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import wx
from openai import OpenAI

from app.log import logger


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
        request_entry = {
            "event": "LLM_REQUEST",
            "api_base": self.settings.api_base,
            "model": self.settings.model,
            "api_key": "[REDACTED]",
        }
        logger.info("LLM_REQUEST", extra={"json": request_entry})
        try:
            self._client.chat.completions.create(
                model=self.settings.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
        except Exception as exc:  # pragma: no cover - network errors
            response_entry = {
                "event": "LLM_RESPONSE",
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
            logger.info("LLM_RESPONSE", extra={"json": response_entry})
            return {"ok": False, "error": response_entry["error"]}
        response_entry = {"event": "LLM_RESPONSE", "ok": True}
        logger.info("LLM_RESPONSE", extra={"json": response_entry})
        return {"ok": True}
