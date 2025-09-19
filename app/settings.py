"""Typed application settings with Pydantic validation."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import tomllib
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


MAX_LIST_PANEL_DEBUG_LEVEL = 35

from .llm.constants import (
    DEFAULT_MAX_CONTEXT_TOKENS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    MIN_MAX_CONTEXT_TOKENS,
    MIN_MAX_OUTPUT_TOKENS,
)


class LLMSettings(BaseModel):
    """Settings for connecting to an LLM service."""

    model_config = ConfigDict(populate_by_name=True, validate_assignment=True)

    base_url: str = Field("", alias="api_base")
    model: str = ""
    api_key: str | None = None
    max_retries: int = 3
    max_output_tokens: int = Field(
        DEFAULT_MAX_OUTPUT_TOKENS,
        ge=MIN_MAX_OUTPUT_TOKENS,
    )
    max_context_tokens: int = Field(
        DEFAULT_MAX_CONTEXT_TOKENS,
        ge=MIN_MAX_CONTEXT_TOKENS,
    )
    token_limit_parameter: str | None = "max_output_tokens"
    timeout_minutes: int = 60
    stream: bool = False

    @staticmethod
    def _normalize_token_limit(
        value: int | str | None,
        *,
        default: int,
        minimum: int,
    ) -> int:
        if value is None:
            return default
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return default
            try:
                numeric = int(raw)
            except ValueError:  # pragma: no cover - delegated to Pydantic
                return value
        else:
            numeric = int(value)
        if numeric <= 0:
            return default
        if numeric < minimum:
            return minimum
        return numeric

    @field_validator("max_output_tokens", mode="before")
    @classmethod
    def _normalize_max_output_tokens(cls, value: int | str | None) -> int:
        """Clamp misconfigured response limits to supported ranges."""

        return cls._normalize_token_limit(
            value,
            default=DEFAULT_MAX_OUTPUT_TOKENS,
            minimum=MIN_MAX_OUTPUT_TOKENS,
        )

    @field_validator("max_context_tokens", mode="before")
    @classmethod
    def _normalize_max_context_tokens(cls, value: int | str | None) -> int:
        """Clamp misconfigured prompt context limits to supported ranges."""

        return cls._normalize_token_limit(
            value,
            default=DEFAULT_MAX_CONTEXT_TOKENS,
            minimum=MIN_MAX_CONTEXT_TOKENS,
        )

    @field_validator("token_limit_parameter", mode="before")
    @classmethod
    def _normalize_token_limit_parameter(
        cls, value: str | None
    ) -> str | None:
        """Normalise blank strings to ``None`` for optional parameter names."""

        if value is None:
            return None
        text = str(value).strip()
        return text or None


def default_requirements_path() -> str:
    """Return bundled requirements directory if present."""

    try:
        candidate = Path(__file__).resolve().parents[1] / "requirements"
    except OSError:  # pragma: no cover - very defensive
        return ""
    return str(candidate) if candidate.is_dir() else ""


class MCPSettings(BaseModel):
    """Settings for configuring the MCP server and client."""

    auto_start: bool = True
    host: str = "127.0.0.1"
    port: int = 59362
    base_path: str = Field(default_factory=default_requirements_path)
    require_token: bool = False
    token: str = ""


class UISettings(BaseModel):
    """Settings related to the graphical user interface."""

    columns: list[str] = Field(default_factory=list)
    recent_dirs: list[str] = Field(default_factory=list)
    auto_open_last: bool = False
    remember_sort: bool = False
    language: str | None = None
    sort_column: int = -1
    sort_ascending: bool = True
    log_level: int = Field(default=logging.INFO)
    list_panel_debug_level: int = 0


class AppSettings(BaseModel):
    """Aggregate settings for the application."""

    llm: LLMSettings = Field(default_factory=LLMSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    ui: UISettings = Field(default_factory=UISettings)

    def to_dict(self) -> dict:
        """Return settings as a plain dictionary."""
        return self.model_dump()


def load_app_settings(path: str | Path) -> AppSettings:
    """Load :class:`AppSettings` from *path* with validation.

    Format is detected by file extension: ``.toml`` uses :mod:`tomllib`,
    everything else is treated as JSON.  Any validation errors are wrapped into
    :class:`ValueError` with a human-friendly message.
    """

    p = Path(path)
    with p.open("rb") as fh:
        data = tomllib.load(fh) if p.suffix.lower() == ".toml" else json.load(fh)
    try:
        return AppSettings.model_validate(data)
    except ValidationError as exc:  # pragma: no cover - exercised via tests
        raise ValueError(str(exc)) from exc
