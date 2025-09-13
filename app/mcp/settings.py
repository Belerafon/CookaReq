from __future__ import annotations

from dataclasses import dataclass
import wx


@dataclass
class MCPSettings:
    """Settings for configuring the MCP server and client."""

    host: str
    port: int
    base_path: str
    require_token: bool
    token: str

    @classmethod
    def from_config(cls, cfg: wx.Config) -> "MCPSettings":
        """Load settings from a :class:`wx.Config` instance."""
        return cls(
            host=cfg.Read("mcp_host", "127.0.0.1"),
            port=cfg.ReadInt("mcp_port", 8000),
            base_path=cfg.Read("mcp_base_path", ""),
            require_token=cfg.ReadBool("mcp_require_token", False),
            token=cfg.Read("mcp_token", ""),
        )
