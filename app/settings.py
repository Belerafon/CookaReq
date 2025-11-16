"""Typed application settings with Pydantic validation."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

import tomllib
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .columns import DEFAULT_LIST_COLUMNS as BASE_DEFAULT_LIST_COLUMNS
from .llm.constants import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_TEMPERATURE,
    DEFAULT_MAX_CONTEXT_TOKENS,
    MIN_MAX_CONTEXT_TOKENS,
)


DEFAULT_DOCUMENT_MAX_READ_KB = 10
MAX_DOCUMENT_MAX_READ_KB = 512


class LLMSettings(BaseModel):
    """Settings for connecting to an LLM service."""

    model_config = ConfigDict(populate_by_name=True, validate_assignment=True)

    base_url: str = Field(DEFAULT_LLM_BASE_URL, alias="api_base")
    model: str = DEFAULT_LLM_MODEL
    message_format: Literal["openai-chat", "harmony", "qwen"] = "openai-chat"
    api_key: str | None = None
    max_retries: int = 3
    max_context_tokens: int = Field(
        DEFAULT_MAX_CONTEXT_TOKENS,
        ge=MIN_MAX_CONTEXT_TOKENS,
    )
    timeout_minutes: int = 60
    stream: bool = False
    use_custom_temperature: bool = False
    temperature: float = Field(
        DEFAULT_LLM_TEMPERATURE,
        ge=0.0,
        le=2.0,
    )

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

    @field_validator("max_context_tokens", mode="before")
    @classmethod
    def _normalize_max_context_tokens(cls, value: int | str | None) -> int:
        """Clamp misconfigured prompt context limits to supported ranges."""
        return cls._normalize_token_limit(
            value,
            default=DEFAULT_MAX_CONTEXT_TOKENS,
            minimum=MIN_MAX_CONTEXT_TOKENS,
        )

    @field_validator("temperature", mode="before")
    @classmethod
    def _normalize_temperature(cls, value: float | str | None) -> float:
        """Coerce *value* to the supported temperature range."""
        if value is None:
            return DEFAULT_LLM_TEMPERATURE
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return DEFAULT_LLM_TEMPERATURE
            try:
                parsed = float(raw)
            except ValueError:  # pragma: no cover - delegated to Pydantic
                return value
        else:
            if isinstance(value, bool):
                raise TypeError("Boolean is not a valid temperature value")
            parsed = float(value)
        if parsed < 0.0:
            return 0.0
        if parsed > 2.0:
            return 2.0
        return parsed


def default_requirements_path() -> str:
    """Return bundled requirements directory if present."""
    try:
        candidate = Path(__file__).resolve().parents[1] / "requirements"
    except OSError:  # pragma: no cover - very defensive
        return ""
    return str(candidate) if candidate.is_dir() else ""


class MCPSettings(BaseModel):
    """Settings for configuring the MCP server and client."""

    model_config = ConfigDict(validate_assignment=True)

    auto_start: bool = True
    host: str = "127.0.0.1"
    port: int = 59362
    base_path: str = Field(default_factory=default_requirements_path)
    documents_path: str = "share"
    documents_max_read_kb: int = DEFAULT_DOCUMENT_MAX_READ_KB
    log_dir: str | None = None
    require_token: bool = False
    token: str = ""

    @field_validator("log_dir", mode="before")
    @classmethod
    def _normalize_log_dir(cls, value: str | Path | None) -> str | None:
        """Convert empty strings to ``None`` and normalise paths."""
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("documents_path", mode="before")
    @classmethod
    def _normalize_documents_path(
        cls, value: str | Path | None
    ) -> str:
        """Return a whitespace-normalised representation of ``value``."""
        if value is None:
            return ""
        text = str(value).strip()
        return text

    @field_validator("documents_max_read_kb", mode="before")
    @classmethod
    def _normalize_documents_max_read_kb(
        cls, value: int | str | None
    ) -> int:
        """Coerce ``value`` into the supported documentation read window."""
        if value is None:
            return DEFAULT_DOCUMENT_MAX_READ_KB
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return DEFAULT_DOCUMENT_MAX_READ_KB
            try:
                parsed = int(raw)
            except ValueError:  # pragma: no cover - delegated to Pydantic
                return value
        else:
            if isinstance(value, bool):
                raise TypeError("Boolean is not a valid documents_max_read_kb")
            parsed = int(value)
        if parsed <= 0:
            return DEFAULT_DOCUMENT_MAX_READ_KB
        if parsed > MAX_DOCUMENT_MAX_READ_KB:
            return MAX_DOCUMENT_MAX_READ_KB
        return parsed


DEFAULT_LIST_COLUMNS = list(BASE_DEFAULT_LIST_COLUMNS)


class AgentSettings(BaseModel):
    """Settings controlling LocalAgent behaviour."""

    model_config = ConfigDict(validate_assignment=True)

    max_thought_steps: int | None = None
    max_consecutive_tool_errors: int | None = 5

    @field_validator("max_thought_steps", mode="before")
    @classmethod
    def _normalise_max_thought_steps(
        cls, value: int | str | None
    ) -> int | None:
        """Coerce *value* into a positive limit or ``None`` for unlimited loops."""
        if value is None:
            return None
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            try:
                numeric = int(raw)
            except ValueError:  # pragma: no cover - delegated to Pydantic
                return value
        else:
            if isinstance(value, bool):
                raise TypeError("Boolean is not a valid max_thought_steps value")
            numeric = int(value)
        if numeric <= 0:
            return None
        return numeric

    @field_validator("max_consecutive_tool_errors", mode="before")
    @classmethod
    def _normalise_max_consecutive_tool_errors(
        cls, value: int | str | None
    ) -> int | None:
        """Coerce *value* into a positive limit or ``None`` to disable the cap."""
        if value is None:
            return None
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            try:
                numeric = int(raw)
            except ValueError:  # pragma: no cover - delegated to Pydantic
                return value
        else:
            if isinstance(value, bool):
                raise TypeError(
                    "Boolean is not a valid max_consecutive_tool_errors value"
                )
            numeric = int(value)
        if numeric <= 0:
            return None
        return numeric


class UISettings(BaseModel):
    """Settings related to the graphical user interface."""

    model_config = ConfigDict(validate_assignment=True)

    columns: list[str] = Field(default_factory=lambda: list(DEFAULT_LIST_COLUMNS))
    recent_dirs: list[str] = Field(default_factory=list)
    last_documents: dict[str, str] = Field(default_factory=dict)
    auto_open_last: bool = False
    remember_sort: bool = False
    language: str | None = None
    sort_column: int = -1
    sort_ascending: bool = True
    log_level: int = Field(default=logging.INFO)
    log_shown: bool = False
    log_sash: int = 300
    agent_chat_shown: bool = False
    agent_chat_sash: int = 500
    agent_history_sash: int = 200
    agent_confirm_mode: Literal["prompt", "never"] = "prompt"
    editor_shown: bool = True
    editor_sash_pos: int = 600
    doc_tree_collapsed: bool = False
    doc_tree_sash: int = 300
    window_width: int = 800
    window_height: int = 600
    window_x: int = -1
    window_y: int = -1
    window_maximized: bool = False
    detached_editor_width: int = 900
    detached_editor_height: int = 700
    detached_editor_x: int = -1
    detached_editor_y: int = -1
    detached_editor_maximized: bool = False

    @field_validator("language", mode="before")
    @classmethod
    def _normalise_language(
        cls, value: str | None,
    ) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None


class AppSettings(BaseModel):
    """Aggregate settings for the application."""

    model_config = ConfigDict(validate_assignment=True)

    llm: LLMSettings = Field(default_factory=LLMSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)
    ui: UISettings = Field(default_factory=UISettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)

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
