from __future__ import annotations

import json

import time
from dataclasses import dataclass

from http.client import HTTPConnection
from typing import Any, Mapping

import wx

from app.telemetry import log_event
from app.mcp.utils import ErrorCode, mcp_error, sanitize
from app.mcp.settings import MCPSettings


class MCPClient:
    """Simple HTTP client for the MCP server."""

    def __init__(
        self,
        cfg: wx.Config | None = None,
        *,
        settings: MCPSettings | None = None,
    ) -> None:
        self._cfg = cfg
        if settings is None:
            if cfg is None:
                raise TypeError("cfg or settings must be provided")
            settings = MCPSettings.from_config(cfg)
        self.settings = settings

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
            "token": self.settings.token if self.settings.require_token else "",
        }
        start = time.monotonic()
        log_event(
            "TOOL_CALL",
            {"tool": "list_requirements", "params": sanitize(params)},
        )
        try:
            conn = HTTPConnection(self.settings.host, self.settings.port, timeout=5)
            try:
                path = "/mcp"
                payload = json.dumps(
                    {"name": "list_requirements", "arguments": {"per_page": 1}}
                )
                headers = {"Content-Type": "application/json"}
                if self.settings.require_token and self.settings.token:
                    headers["Authorization"] = f"Bearer {self.settings.token}"
                conn.request("POST", path, body=payload, headers=headers)
                resp = conn.getresponse()
                body = resp.read().decode()
            finally:
                conn.close()
            data = json.loads(body or "{}")
            if resp.status == 200 and "error" not in data:
                log_event("TOOL_RESULT", {"ok": True}, start_time=start)
                return {"ok": True}
            err = data.get("error")
            if not err:
                err = {"code": str(resp.status), "message": data.get("message", "")}
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            return err
        except Exception as exc:  # pragma: no cover - network errors
            err = mcp_error(ErrorCode.INTERNAL, str(exc))["error"]
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            return err

    # ------------------------------------------------------------------
    def _call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Invoke *name* tool with *arguments* on the MCP server."""

        log_event(
            "TOOL_CALL",
            {"tool": name, "params": sanitize(dict(arguments))},
        )
        start = time.monotonic()
        try:
            conn = HTTPConnection(self.settings.host, self.settings.port, timeout=5)
            try:
                payload = json.dumps({"name": name, "arguments": dict(arguments)})
                headers = {"Content-Type": "application/json"}
                if self.settings.require_token and self.settings.token:
                    headers["Authorization"] = f"Bearer {self.settings.token}"
                conn.request("POST", "/mcp", body=payload, headers=headers)
                resp = conn.getresponse()
                body = resp.read().decode()
            finally:
                conn.close()
            data = json.loads(body or "{}")
            if resp.status == 200 and "error" not in data:
                log_event("TOOL_RESULT", {"result": data}, start_time=start)
                log_event("DONE")
                return data
            err = data.get("error")
            if not err:
                err = {"code": str(resp.status), "message": data.get("message", "")}
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            log_event("ERROR", {"error": err})
            return {"error": err}
        except Exception as exc:  # pragma: no cover - network errors
            err = mcp_error(ErrorCode.INTERNAL, str(exc))["error"]
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            log_event("ERROR", {"error": err})
            return {"error": err}

    # ------------------------------------------------------------------
    def run_command(self, text: str) -> dict[str, Any]:
        """Use an LLM to parse *text* and execute the resulting tool call."""

        from app.llm.client import LLMClient

        try:
            name, arguments = LLMClient(self._cfg).parse_command(text)
        except Exception as exc:
            err = mcp_error(ErrorCode.VALIDATION_ERROR, str(exc))["error"]
            log_event("ERROR", {"error": err})
            return {"error": err}
        return self._call_tool(name, arguments)

