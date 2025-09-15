"""HTTP client for interacting with the MCP server."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from http.client import HTTPConnection
from typing import Any

from ..i18n import _
from ..settings import MCPSettings
from ..telemetry import log_event
from .utils import ErrorCode, mcp_error


class MCPClient:
    """Simple HTTP client for the MCP server."""

    def __init__(
        self,
        settings: MCPSettings,
        *,
        confirm: Callable[[str], bool],
    ) -> None:
        """Initialize client with MCP ``settings`` and confirmation callback."""
        self.settings = settings
        self._confirm = confirm

    # ------------------------------------------------------------------
    def check_tools(self) -> dict[str, Any]:
        """Perform a minimal ``list_requirements`` call to verify the server.

        Returns
        -------
        dict
            A dictionary in the ``{"ok": bool, "error": dict | None}`` format.
            ``error`` contains the structured MCP error payload when
            ``ok`` is ``False`` and is ``None`` otherwise.
        """

        params = {
            "host": self.settings.host,
            "port": self.settings.port,
            "base_path": self.settings.base_path,
            "token": self.settings.token if self.settings.require_token else "",
        }
        start = time.monotonic()
        # ``log_event`` выполняет собственную очистку чувствительных данных.
        log_event(
            "TOOL_CALL",
            {"tool": "list_requirements", "params": params},
        )
        try:
            conn = HTTPConnection(self.settings.host, self.settings.port, timeout=5)
            try:
                path = "/mcp"
                payload = json.dumps(
                    {"name": "list_requirements", "arguments": {"per_page": 1}},
                )
                headers = {"Content-Type": "application/json"}
                if self.settings.require_token and self.settings.token:
                    headers["Authorization"] = f"Bearer {self.settings.token}"
                conn.request("POST", path, body=payload, headers=headers)
                resp = conn.getresponse()
                body = resp.read().decode()
            finally:
                conn.close()
        except Exception as exc:  # pragma: no cover - network errors
            err = mcp_error(ErrorCode.INTERNAL, str(exc))["error"]
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            return {"ok": False, "error": err}
        else:
            data = json.loads(body or "{}")
            if resp.status == 200 and "error" not in data:
                log_event("TOOL_RESULT", {"ok": True}, start_time=start)
                return {"ok": True, "error": None}
            err = data.get("error")
            if not err:
                err = {"code": str(resp.status), "message": data.get("message", "")}
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            return {"ok": False, "error": err}

    # ------------------------------------------------------------------
    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Invoke *name* tool with *arguments* on the MCP server.

        Returns
        -------
        dict
            A dictionary with ``ok``/``error`` fields following the same
            structure as :meth:`check_tools`.  When ``ok`` is ``True`` the
            optional ``result`` key contains the payload returned by the server.
        """

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
                return {"ok": False, "error": err}

        # ``log_event`` выполняет собственную очистку чувствительных данных.
        log_event(
            "TOOL_CALL",
            {"tool": name, "params": dict(arguments)},
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
        except Exception as exc:  # pragma: no cover - network errors
            err = mcp_error(ErrorCode.INTERNAL, str(exc))["error"]
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            log_event("ERROR", {"error": err})
            return {"ok": False, "error": err}
        else:
            data = json.loads(body or "{}")
            if resp.status == 200 and "error" not in data:
                log_event("TOOL_RESULT", {"result": data}, start_time=start)
                log_event("DONE")
                return {"ok": True, "error": None, "result": data}
            err = data.get("error")
            if not err:
                err = {"code": str(resp.status), "message": data.get("message", "")}
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            log_event("ERROR", {"error": err})
            return {"ok": False, "error": err}

    # ------------------------------------------------------------------
    def _call_tool(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Backward compatible wrapper for :meth:`call_tool`."""

        return self.call_tool(name, arguments)
