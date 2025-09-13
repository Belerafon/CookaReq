from __future__ import annotations

import json
from dataclasses import dataclass
from http.client import HTTPConnection
from typing import Any

import wx

from app.log import logger
from app.mcp.utils import ErrorCode, mcp_error, sanitize


@dataclass
class MCPSettings:
    """Settings for connecting to the MCP server."""

    host: str
    port: int
    base_path: str
    token: str

    @classmethod
    def from_config(cls, cfg: wx.Config) -> "MCPSettings":
        """Load settings from ``wx.Config`` instance."""
        return cls(
            host=cfg.Read("mcp_host", "127.0.0.1"),
            port=cfg.ReadInt("mcp_port", 8000),
            base_path=cfg.Read("mcp_base_path", ""),
            token=cfg.Read("mcp_token", ""),
        )


class MCPClient:
    """Simple HTTP client for the MCP server."""

    def __init__(self, cfg: wx.Config) -> None:
        self.settings = MCPSettings.from_config(cfg)

    # ------------------------------------------------------------------
    def check_tools(self) -> dict[str, Any]:
        """Perform a minimal ``list_requirements`` call to verify the server.

        Returns
        -------
        dict
            ``{"ok": True}`` on success otherwise an error dictionary with
            ``code`` and ``message``.
        """

        params = {
            "host": self.settings.host,
            "port": self.settings.port,
            "base_path": self.settings.base_path,
            "token": self.settings.token,
        }
        logger.info(
            "TOOL_CALL",
            extra={
                "json": {
                    "event": "TOOL_CALL",
                    "tool": "list_requirements",
                    "params": sanitize(params),
                }
            },
        )
        try:
            conn = HTTPConnection(self.settings.host, self.settings.port, timeout=5)
            try:
                path = "/mcp"
                payload = json.dumps(
                    {"name": "list_requirements", "arguments": {"per_page": 1}}
                )
                headers = {"Content-Type": "application/json"}
                if self.settings.token:
                    headers["Authorization"] = f"Bearer {self.settings.token}"
                conn.request("POST", path, body=payload, headers=headers)
                resp = conn.getresponse()
                body = resp.read().decode()
            finally:
                conn.close()
            data = json.loads(body or "{}")
            if resp.status == 200 and "error" not in data:
                logger.info(
                    "TOOL_RESULT", extra={"json": {"event": "TOOL_RESULT", "ok": True}}
                )
                return {"ok": True}
            err = data.get("error")
            if not err:
                err = {"code": str(resp.status), "message": data.get("message", "")}
            logger.info(
                "TOOL_RESULT",
                extra={"json": {"event": "TOOL_RESULT", "error": err}},
            )
            return err
        except Exception as exc:  # pragma: no cover - network errors
            err = mcp_error(ErrorCode.INTERNAL, str(exc))["error"]
            logger.info(
                "TOOL_RESULT",
                extra={"json": {"event": "TOOL_RESULT", "error": err}},
            )
            return err
