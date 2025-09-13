from __future__ import annotations

import json

import time
from http.client import HTTPConnection
from typing import Any, Mapping, Callable

from app.i18n import _
from app.telemetry import log_event
from app.mcp.utils import ErrorCode, mcp_error, sanitize
from app.settings import MCPSettings


class MCPClient:
    """Simple HTTP client for the MCP server."""

    def __init__(self, settings: MCPSettings, *, confirm: Callable[[str], bool]) -> None:
        self.settings = settings
        self._confirm = confirm

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
    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Invoke *name* tool with *arguments* on the MCP server."""

        if name in {"delete_requirement", "patch_requirement"}:
            log_event("CONFIRM", {"tool": name})
            if name == "delete_requirement":
                msg = _("Delete requirement?")
            else:
                msg = _("Update requirement?")
            confirmed = self._confirm(msg)
            log_event("CONFIRM_RESULT", {"tool": name, "confirmed": confirmed})
            if not confirmed:
                err = mcp_error("CANCELLED", _("Cancelled by user"))["error"]
                log_event("CANCELLED", {"tool": name})
                return {"error": err}

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
    def _call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Backward compatible wrapper for :meth:`call_tool`."""

        return self.call_tool(name, arguments)

