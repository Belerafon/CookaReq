from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
import json
import tomllib


@dataclass
class LLMSettings:
    """Settings for connecting to an LLM service."""

    api_base: str = ""
    model: str = ""
    api_key: str = ""
    timeout: int = 60


@dataclass
class MCPSettings:
    """Settings for configuring the MCP server and client."""

    host: str = "127.0.0.1"
    port: int = 8000
    base_path: str = ""
    require_token: bool = False
    token: str = ""


@dataclass
class UISettings:
    """Settings related to the graphical user interface."""

    columns: list[str] = field(default_factory=list)
    recent_dirs: list[str] = field(default_factory=list)
    auto_open_last: bool = False
    remember_sort: bool = False
    language: str | None = None
    sort_column: int = -1
    sort_ascending: bool = True


@dataclass
class AppSettings:
    """Aggregate settings for the application."""

    llm: LLMSettings = field(default_factory=LLMSettings)
    mcp: MCPSettings = field(default_factory=MCPSettings)
    ui: UISettings = field(default_factory=UISettings)

    def to_dict(self) -> dict:
        return {
            "llm": asdict(self.llm),
            "mcp": asdict(self.mcp),
            "ui": asdict(self.ui),
        }


def load_app_settings(path: str | Path) -> AppSettings:
    """Load :class:`AppSettings` from *path*.

    The file must contain ``llm`` and/or ``mcp`` sections.  Format is detected
    by extension: ``.toml`` uses :mod:`tomllib`, everything else is treated as
    JSON.
    """

    p = Path(path)
    with p.open("rb") as fh:
        if p.suffix.lower() == ".toml":
            data = tomllib.load(fh)
        else:
            data = json.load(fh)
    llm_data = data.get("llm", {})
    mcp_data = data.get("mcp", {})
    ui_data = data.get("ui", {})
    return AppSettings(
        llm=LLMSettings(**llm_data),
        mcp=MCPSettings(**mcp_data),
        ui=UISettings(**ui_data),
    )
