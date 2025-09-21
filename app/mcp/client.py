"""HTTP client for interacting with the MCP server."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable, Mapping
from http.client import HTTPConnection
from typing import Any

from ..i18n import _
from ..settings import MCPSettings
from ..telemetry import log_debug_payload, log_event
from .utils import ErrorCode, mcp_error


class MCPNotReadyError(ConnectionError):
    """Raised when the MCP server fails a readiness probe."""

    def __init__(self, error_payload: Mapping[str, Any]):
        message = error_payload.get("message") if isinstance(error_payload, Mapping) else None
        super().__init__(message or "MCP server is not ready")
        payload = dict(error_payload) if isinstance(error_payload, Mapping) else {}
        self.error_payload = payload
        self.error = payload


class MCPClient:
    """Simple HTTP client for the MCP server."""

    _READY_CACHE_TTL = 5.0

    def __init__(
        self,
        settings: MCPSettings,
        *,
        confirm: Callable[[str], bool],
    ) -> None:
        """Initialize client with MCP ``settings`` and confirmation callback."""
        self.settings = settings
        self._confirm = confirm
        self._last_ready_check: float | None = None
        self._last_ready_ok = False
        self._last_ready_error: dict[str, Any] | None = None

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
        request_body = {"name": "list_requirements", "arguments": {"per_page": 1}}
        headers = {"Content-Type": "application/json"}
        if self.settings.require_token and self.settings.token:
            headers["Authorization"] = f"Bearer {self.settings.token}"
        start = time.monotonic()
        # ``log_event`` выполняет собственную очистку чувствительных данных.
        log_debug_payload(
            "MCP_REQUEST",
            {
                "direction": "outbound",
                "tool": "list_requirements",
                "http": {
                    "host": self.settings.host,
                    "port": self.settings.port,
                    "path": "/mcp",
                    "headers": headers,
                    "body": request_body,
                },
            },
        )
        log_event(
            "TOOL_CALL",
            {"tool": "list_requirements", "params": params},
        )
        try:
            conn = HTTPConnection(self.settings.host, self.settings.port, timeout=5)
            try:
                payload = json.dumps(request_body)
                conn.request("POST", "/mcp", body=payload, headers=headers)
                resp = conn.getresponse()
                getheaders = getattr(resp, "getheaders", None)
                response_headers = list(getheaders()) if callable(getheaders) else []
                body = resp.read().decode()
            finally:
                conn.close()
        except Exception as exc:  # pragma: no cover - network errors
            err = mcp_error(ErrorCode.INTERNAL, str(exc))["error"]
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            log_debug_payload(
                "MCP_RESPONSE",
                {
                    "direction": "inbound",
                    "tool": "list_requirements",
                    "error": err,
                },
            )
            self._update_ready_state(False, err)
            return {"ok": False, "error": err}
        else:
            data = json.loads(body or "{}")
            log_debug_payload(
                "MCP_RESPONSE",
                {
                    "direction": "inbound",
                    "tool": "list_requirements",
                    "status": resp.status,
                    "headers": response_headers,
                    "body": body,
                },
            )
            if resp.status == 200 and "error" not in data:
                log_event("TOOL_RESULT", {"ok": True}, start_time=start)
                self._update_ready_state(True, None)
                return {"ok": True, "error": None}
            err = data.get("error")
            if not err:
                err = {"code": str(resp.status), "message": data.get("message", "")}
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            self._update_ready_state(False, err)
            return {"ok": False, "error": err}

    # ------------------------------------------------------------------
    async def check_tools_async(self) -> dict[str, Any]:
        """Asynchronous counterpart to :meth:`check_tools`."""

        return await asyncio.to_thread(self.check_tools)

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
        request_body = {"name": name, "arguments": dict(arguments)}
        headers = {"Content-Type": "application/json"}
        if self.settings.require_token and self.settings.token:
            headers["Authorization"] = f"Bearer {self.settings.token}"
        start = time.monotonic()
        log_debug_payload(
            "MCP_REQUEST",
            {
                "direction": "outbound",
                "tool": name,
                "http": {
                    "host": self.settings.host,
                    "port": self.settings.port,
                    "path": "/mcp",
                    "headers": headers,
                    "body": request_body,
                },
            },
        )
        try:
            conn = HTTPConnection(self.settings.host, self.settings.port, timeout=5)
            try:
                payload = json.dumps(request_body)
                conn.request("POST", "/mcp", body=payload, headers=headers)
                resp = conn.getresponse()
                getheaders = getattr(resp, "getheaders", None)
                response_headers = list(getheaders()) if callable(getheaders) else []
                body = resp.read().decode()
            finally:
                conn.close()
        except Exception as exc:  # pragma: no cover - network errors
            err = mcp_error(ErrorCode.INTERNAL, str(exc))["error"]
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            log_event("ERROR", {"error": err})
            log_debug_payload(
                "MCP_RESPONSE",
                {"direction": "inbound", "tool": name, "error": err},
            )
            self._update_ready_state(False, err)
            return {"ok": False, "error": err}
        else:
            data = json.loads(body or "{}")
            log_debug_payload(
                "MCP_RESPONSE",
                {
                    "direction": "inbound",
                    "tool": name,
                    "status": resp.status,
                    "headers": response_headers,
                    "body": body,
                },
            )
            if resp.status == 200 and "error" not in data:
                log_event("TOOL_RESULT", {"result": data}, start_time=start)
                log_event("DONE")
                self._update_ready_state(True, None)
                return {"ok": True, "error": None, "result": data}
            err = data.get("error")
            if not err:
                err = {"code": str(resp.status), "message": data.get("message", "")}
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            log_event("ERROR", {"error": err})
            if resp.status == 200:
                self._update_ready_state(True, None)
            else:
                self._update_ready_state(False, err)
            return {"ok": False, "error": err}

    # ------------------------------------------------------------------
    async def call_tool_async(
        self, name: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Asynchronous counterpart to :meth:`call_tool`."""

        return await asyncio.to_thread(self.call_tool, name, arguments)

    # ------------------------------------------------------------------
    def ensure_ready(self, *, force: bool = False) -> None:
        """Raise :class:`MCPNotReadyError` if the MCP server is unavailable."""

        now = time.monotonic()
        if (
            not force
            and self._last_ready_ok
            and self._last_ready_check is not None
            and now - self._last_ready_check < self._READY_CACHE_TTL
        ):
            return

        params = {
            "host": self.settings.host,
            "port": self.settings.port,
            "base_path": self.settings.base_path,
        }
        headers = {}
        if self.settings.require_token and self.settings.token:
            headers["Authorization"] = f"Bearer {self.settings.token}"

        start = time.monotonic()
        log_event("HEALTH_CHECK", {"params": params})
        log_debug_payload(
            "MCP_HEALTH_REQUEST",
            {
                "direction": "outbound",
                "http": {
                    "host": self.settings.host,
                    "port": self.settings.port,
                    "path": "/health",
                    "headers": headers,
                },
            },
        )
        try:
            conn = HTTPConnection(self.settings.host, self.settings.port, timeout=5)
            try:
                conn.request("GET", "/health", headers=headers)
                resp = conn.getresponse()
                getheaders = getattr(resp, "getheaders", None)
                response_headers = list(getheaders()) if callable(getheaders) else []
                body = resp.read().decode()
            finally:
                conn.close()
        except Exception as exc:  # pragma: no cover - network errors
            error = self._health_error(
                _(
                    "MCP server is not reachable at %(host)s:%(port)s",
                )
                % {"host": self.settings.host, "port": self.settings.port},
                details={"cause": str(exc), **params},
            )
            log_event("HEALTH_RESULT", {"error": error}, start_time=start)
            log_debug_payload(
                "MCP_HEALTH_RESPONSE",
                {"direction": "inbound", "error": error},
            )
            self._update_ready_state(False, error)
            raise MCPNotReadyError(error) from exc
        log_debug_payload(
            "MCP_HEALTH_RESPONSE",
            {
                "direction": "inbound",
                "status": resp.status,
                "headers": response_headers,
                "body": body,
            },
        )

        if resp.status == 200:
            try:
                data = json.loads(body or "{}")
            except json.JSONDecodeError as exc:  # pragma: no cover - malformed health response
                error = self._health_error(
                    _("MCP health endpoint returned invalid JSON"),
                    details={"cause": str(exc), **params, "body": body},
                )
                log_event("HEALTH_RESULT", {"error": error}, start_time=start)
                self._update_ready_state(False, error)
                raise MCPNotReadyError(error) from exc
            if isinstance(data, Mapping) and data.get("status") == "ok":
                log_event("HEALTH_RESULT", {"ok": True}, start_time=start)
                self._update_ready_state(True, None)
                return
            error = self._health_error(
                _("MCP server health check failed"),
                details={"response": data, **params},
            )
            log_event("HEALTH_RESULT", {"error": error}, start_time=start)
            self._update_ready_state(False, error)
            raise MCPNotReadyError(error)

        try:
            data = json.loads(body or "{}")
        except json.JSONDecodeError:  # pragma: no cover - fallback to raw body
            data = body
        code = ErrorCode.UNAUTHORIZED if resp.status in {401, 403} else ErrorCode.INTERNAL
        message = _("MCP server health check failed")
        details: dict[str, Any] = {"status": resp.status, **params}
        if data:
            details["response"] = data
        error = mcp_error(code, message, details)["error"]
        log_event("HEALTH_RESULT", {"error": error}, start_time=start)
        self._update_ready_state(False, error)
        raise MCPNotReadyError(error)

    # ------------------------------------------------------------------
    async def ensure_ready_async(self, *, force: bool = False) -> None:
        """Asynchronous counterpart to :meth:`ensure_ready`."""

        await asyncio.to_thread(self.ensure_ready, force=force)

    # ------------------------------------------------------------------
    def _update_ready_state(
        self, ok: bool, error: Mapping[str, Any] | None
    ) -> None:
        """Remember the outcome of the most recent readiness probe."""

        self._last_ready_check = time.monotonic()
        self._last_ready_ok = ok
        self._last_ready_error = dict(error) if isinstance(error, Mapping) else None

    def _health_error(
        self,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return MCP-formatted health check error payload."""

        payload = mcp_error(ErrorCode.INTERNAL, message, details)["error"]
        return payload

