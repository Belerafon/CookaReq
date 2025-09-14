"""Typed application settings with Pydantic validation."""

from __future__ import annotations

from pathlib import Path
import json
import tomllib
from pydantic import BaseModel, ValidationError, Field, ConfigDict


class LLMSettings(BaseModel):
    """Settings for connecting to an LLM service."""

    model_config = ConfigDict(populate_by_name=True)

    base_url: str = Field("", alias="api_base")
    model: str = ""
    api_key: str | None = None
    max_retries: int = 3
    max_output_tokens: int | None = None
    timeout_minutes: int = 60
    stream: bool = False


class MCPSettings(BaseModel):
    """Settings for configuring the MCP server and client."""

    host: str = "127.0.0.1"
    port: int = 59362
    base_path: str = ""
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
        if p.suffix.lower() == ".toml":
            data = tomllib.load(fh)
        else:
            data = json.load(fh)
    try:
        return AppSettings.model_validate(data)
    except ValidationError as exc:  # pragma: no cover - exercised via tests
        raise ValueError(str(exc)) from exc
