"""HTTP client for interacting with the MCP server."""
from __future__ import annotations

import logging
import json
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from ..confirm import (
    ConfirmDecision,
    RequirementChange,
    RequirementUpdatePrompt,
    confirm_requirement_update as global_confirm_requirement_update,
)
from ..i18n import _
from ..settings import MCPSettings
from ..telemetry import log_debug_payload, log_event
from .events import notify_tool_success
from .utils import ErrorCode, mcp_error
from ..llm.validation import ToolValidationError


logger = logging.getLogger(__name__)


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

    _REQUEST_TIMEOUT = httpx.Timeout(5.0)
    _UPDATE_TOOLS = {
        "update_requirement_field",
        "set_requirement_labels",
        "set_requirement_attachments",
        "set_requirement_links",
    }
    _BROADCAST_TOOLS = {
        "create_requirement",
        "update_requirement_field",
        "set_requirement_labels",
        "set_requirement_attachments",
        "set_requirement_links",
        "delete_requirement",
        "link_requirements",
    }

    def __init__(
        self,
        settings: MCPSettings,
        *,
        confirm: Callable[[str], bool],
        confirm_requirement_update: Callable[[RequirementUpdatePrompt], ConfirmDecision]
        | None = None,
    ) -> None:
        """Initialize client with MCP ``settings`` and confirmation callback."""
        self.settings = settings
        self._confirm = confirm
        self._confirm_requirement_update = (
            confirm_requirement_update or global_confirm_requirement_update
        )
        self._last_ready_check: float | None = None
        self._last_ready_ok = False
        self._last_ready_error: dict[str, Any] | None = None
        self._base_url = self._build_base_url()

    # ------------------------------------------------------------------
    def _confirm_sensitive_tool(
        self, name: str, arguments: Mapping[str, Any]
    ) -> bool:
        """Return ``True`` when the write operation should proceed."""
        prompt: RequirementUpdatePrompt | None = None
        confirm_payload: dict[str, Any] = {"tool": name}
        if name in self._UPDATE_TOOLS:
            prompt = self._build_requirement_update_prompt(name, arguments)
            confirm_payload.update(
                {
                    "rid": prompt.rid,
                    "directory": prompt.directory,
                    "changes": [
                        {"kind": change.kind, "field": change.field}
                        for change in prompt.changes
                    ],
                }
            )
        log_event("CONFIRM", confirm_payload)

        decision_value: str | None = None
        if name == "delete_requirement":
            msg = _("Delete requirement?")
            confirmed = self._confirm(msg)
        elif name in self._UPDATE_TOOLS:
            if prompt is None:
                prompt = self._build_requirement_update_prompt(name, arguments)
            decision = self._confirm_requirement_update(prompt)
            decision_value = decision.value
            confirmed = decision is not ConfirmDecision.NO
        else:
            return True

        result_payload: dict[str, Any] = {"tool": name, "confirmed": confirmed}
        if decision_value is not None:
            result_payload["decision"] = decision_value
        log_event("CONFIRM_RESULT", result_payload)
        return confirmed

    def _broadcast_tool_result(
        self,
        name: str,
        arguments: Mapping[str, Any],
        result: Mapping[str, Any] | None,
    ) -> None:
        """Notify listeners about successful requirement-changing tools."""
        if name not in self._BROADCAST_TOOLS:
            return
        if result is None or not isinstance(result, Mapping):
            return
        try:
            notify_tool_success(
                name,
                base_path=self.settings.base_path,
                arguments=arguments,
                result=result,
            )
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Failed to broadcast MCP tool result")

    def _prepare_tool_arguments(
        self, name: str, arguments: Mapping[str, Any]
    ) -> Any:
        """Return tool arguments without performing local validation."""
        if arguments is None:
            return {}
        if isinstance(arguments, Mapping):
            return dict(arguments)

        message = _(
            "Invalid arguments for %(tool)s: expected a JSON object but received %(type)s"
        ) % {"tool": name, "type": type(arguments).__name__}
        error = ToolValidationError(message)
        error.llm_message = message
        error.llm_tool_calls = (
            [
                {
                    "id": None,
                    "name": name,
                    "arguments": arguments,
                }
            ]
        )
        raise error

    @staticmethod
    def _build_requirement_update_prompt(
        name: str, arguments: Mapping[str, Any]
    ) -> RequirementUpdatePrompt:
        """Create :class:`RequirementUpdatePrompt` from MCP tool *arguments*."""
        directory = arguments.get("directory")
        rid = arguments.get("rid")
        return RequirementUpdatePrompt(
            rid=str(rid) if rid is not None else "",
            directory=str(directory) if directory is not None else None,
            tool=name,
            changes=MCPClient._normalise_requirement_changes(name, arguments),
        )

    @staticmethod
    def _normalise_requirement_changes(
        name: str, arguments: Mapping[str, Any]
    ) -> tuple[RequirementChange, ...]:
        """Return canonical representation of planned updates for prompts."""
        if name == "update_requirement_field":
            field = arguments.get("field")
            return (
                RequirementChange(
                    kind="field",
                    field=str(field) if field is not None else None,
                    value=arguments.get("value"),
                ),
            )
        if name == "set_requirement_labels":
            return (
                RequirementChange(kind="labels", value=arguments.get("labels")),
            )
        if name == "set_requirement_attachments":
            return (
                RequirementChange(
                    kind="attachments", value=arguments.get("attachments")
                ),
            )
        if name == "set_requirement_links":
            return (
                RequirementChange(kind="links", value=arguments.get("links")),
            )
        return ()

    # ------------------------------------------------------------------
    def _build_base_url(self) -> str:
        """Return base URL for requests, wrapping IPv6 literals if required."""
        host = self.settings.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"http://{host}:{self.settings.port}"

    def _headers(self, *, json_body: bool = False) -> dict[str, str]:
        """Return default headers for requests."""
        headers: dict[str, str] = {}
        if json_body:
            headers["Content-Type"] = "application/json"
        if self.settings.require_token and self.settings.token:
            headers["Authorization"] = f"Bearer {self.settings.token}"
        return headers

    def _request_sync(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any | None = None,
    ) -> httpx.Response:
        """Execute *method* request synchronously and return the response."""
        request_headers = dict(headers or {})
        with httpx.Client(base_url=self._base_url, timeout=self._REQUEST_TIMEOUT) as client:
            return client.request(method, path, json=json_body, headers=request_headers)

    async def _request_async(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        json_body: Any | None = None,
    ) -> httpx.Response:
        """Execute *method* request asynchronously and return the response."""
        request_headers = dict(headers or {})
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._REQUEST_TIMEOUT
        ) as client:
            return await client.request(method, path, json=json_body, headers=request_headers)

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
        headers = self._headers(json_body=True)
        start = time.monotonic()
        # ``log_event`` performs its own sanitisation of sensitive fields.
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
            resp = self._request_sync("POST", "/mcp", headers=headers, json_body=request_body)
            response_headers = list(resp.headers.items())
            body = resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network errors
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
                    "status": resp.status_code,
                    "headers": response_headers,
                    "body": body,
                },
            )
            if resp.status_code == 200 and "error" not in data:
                log_event("TOOL_RESULT", {"ok": True}, start_time=start)
                self._update_ready_state(True, None)
                return {"ok": True, "error": None}
            err = data.get("error")
            if not err:
                err = {"code": str(resp.status_code), "message": data.get("message", "")}
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            self._update_ready_state(False, err)
            return {"ok": False, "error": err}

    # ------------------------------------------------------------------
    async def check_tools_async(self) -> dict[str, Any]:
        """Asynchronous counterpart to :meth:`check_tools`."""
        request_body = {"name": "list_requirements", "arguments": {"per_page": 1}}
        headers = self._headers(json_body=True)
        params = {
            "host": self.settings.host,
            "port": self.settings.port,
            "base_path": self.settings.base_path,
            "token": self.settings.token if self.settings.require_token else "",
        }
        start = time.monotonic()
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
            resp = await self._request_async(
                "POST", "/mcp", headers=headers, json_body=request_body
            )
            response_headers = list(resp.headers.items())
            body = resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network errors
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

        data = json.loads(body or "{}")
        log_debug_payload(
            "MCP_RESPONSE",
            {
                "direction": "inbound",
                "tool": "list_requirements",
                "status": resp.status_code,
                "headers": response_headers,
                "body": body,
            },
        )
        if resp.status_code == 200 and "error" not in data:
            log_event("TOOL_RESULT", {"ok": True}, start_time=start)
            self._update_ready_state(True, None)
            return {"ok": True, "error": None}
        err = data.get("error")
        if not err:
            err = {"code": str(resp.status_code), "message": data.get("message", "")}
        log_event("TOOL_RESULT", {"error": err}, start_time=start)
        self._update_ready_state(False, err)
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
        prepared_arguments = self._prepare_tool_arguments(name, arguments)

        if name == "delete_requirement" or name in self._UPDATE_TOOLS:
            confirmed = self._confirm_sensitive_tool(name, prepared_arguments)
            if not confirmed:
                err = mcp_error("CANCELLED", _("Cancelled by user"))["error"]
                log_event("CANCELLED", {"tool": name})
                return {"ok": False, "error": err}

        # ``log_event`` performs its own sanitisation of sensitive fields.
        log_event(
            "TOOL_CALL",
            {"tool": name, "params": dict(prepared_arguments)},
        )
        request_body = {"name": name, "arguments": dict(prepared_arguments)}
        headers = self._headers(json_body=True)
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
            resp = self._request_sync("POST", "/mcp", headers=headers, json_body=request_body)
            response_headers = list(resp.headers.items())
            body = resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network errors
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
                    "status": resp.status_code,
                    "headers": response_headers,
                    "body": body,
                },
            )
            if resp.status_code == 200 and "error" not in data:
                log_event("TOOL_RESULT", {"result": data}, start_time=start)
                log_event("DONE")
                self._update_ready_state(True, None)
                self._broadcast_tool_result(name, prepared_arguments, data)
                return {"ok": True, "error": None, "result": data}
            err = data.get("error")
            if not err:
                err = {"code": str(resp.status_code), "message": data.get("message", "")}
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            log_event("ERROR", {"error": err})
            if resp.status_code == 200:
                self._update_ready_state(True, None)
            else:
                self._update_ready_state(False, err)
            return {"ok": False, "error": err}

    # ------------------------------------------------------------------
    async def call_tool_async(
        self, name: str, arguments: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Asynchronous counterpart to :meth:`call_tool`."""
        prepared_arguments = self._prepare_tool_arguments(name, arguments)

        if name == "delete_requirement" or name in self._UPDATE_TOOLS:
            confirmed = self._confirm_sensitive_tool(name, prepared_arguments)
            if not confirmed:
                err = mcp_error("CANCELLED", _("Cancelled by user"))["error"]
                log_event("CANCELLED", {"tool": name})
                return {"ok": False, "error": err}

        log_event(
            "TOOL_CALL",
            {"tool": name, "params": dict(prepared_arguments)},
        )
        headers = self._headers(json_body=True)
        request_body = {"name": name, "arguments": dict(prepared_arguments)}
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
            resp = await self._request_async(
                "POST", "/mcp", headers=headers, json_body=request_body
            )
            response_headers = list(resp.headers.items())
            body = resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network errors
            err = mcp_error(ErrorCode.INTERNAL, str(exc))["error"]
            log_event("TOOL_RESULT", {"error": err}, start_time=start)
            log_event("ERROR", {"error": err})
            log_debug_payload(
                "MCP_RESPONSE",
                {"direction": "inbound", "tool": name, "error": err},
            )
            self._update_ready_state(False, err)
            return {"ok": False, "error": err}

        data = json.loads(body or "{}")
        log_debug_payload(
            "MCP_RESPONSE",
            {
                "direction": "inbound",
                "tool": name,
                "status": resp.status_code,
                "headers": response_headers,
                "body": body,
            },
        )
        if resp.status_code == 200 and "error" not in data:
            log_event("TOOL_RESULT", {"result": data}, start_time=start)
            log_event("DONE")
            self._update_ready_state(True, None)
            self._broadcast_tool_result(name, prepared_arguments, data)
            return {"ok": True, "error": None, "result": data}
        err = data.get("error")
        if not err:
            err = {"code": str(resp.status_code), "message": data.get("message", "")}
        log_event("TOOL_RESULT", {"error": err}, start_time=start)
        log_event("ERROR", {"error": err})
        if resp.status_code == 200:
            self._update_ready_state(True, None)
        else:
            self._update_ready_state(False, err)
        return {"ok": False, "error": err}

    # ------------------------------------------------------------------
    def ensure_ready(self, *, force: bool = False) -> None:
        """Raise :class:`MCPNotReadyError` if the MCP server is unavailable."""
        if (
            not force
            and self._last_ready_ok
            and self._last_ready_check is not None
        ):
            return

        params = {
            "host": self.settings.host,
            "port": self.settings.port,
            "base_path": self.settings.base_path,
        }
        headers = self._headers()

        start = time.monotonic()
        log_event("HEALTH_CHECK", {"params": params}, level=logging.DEBUG)
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
            resp = self._request_sync("GET", "/health", headers=headers)
            response_headers = list(resp.headers.items())
            body = resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network errors
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
                "status": resp.status_code,
                "headers": response_headers,
                "body": body,
            },
        )

        if resp.status_code == 200:
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
                log_event(
                    "HEALTH_RESULT",
                    {"ok": True},
                    start_time=start,
                    level=logging.DEBUG,
                )
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
        code = ErrorCode.UNAUTHORIZED if resp.status_code in {401, 403} else ErrorCode.INTERNAL
        message = _("MCP server health check failed")
        details: dict[str, Any] = {"status": resp.status_code, **params}
        if data:
            details["response"] = data
        error = mcp_error(code, message, details)["error"]
        log_event("HEALTH_RESULT", {"error": error}, start_time=start)
        self._update_ready_state(False, error)
        raise MCPNotReadyError(error)

    # ------------------------------------------------------------------
    async def ensure_ready_async(self, *, force: bool = False) -> None:
        """Asynchronous counterpart to :meth:`ensure_ready`."""
        if (
            not force
            and self._last_ready_ok
            and self._last_ready_check is not None
        ):
            return

        params = {
            "host": self.settings.host,
            "port": self.settings.port,
            "base_path": self.settings.base_path,
        }
        headers = self._headers()

        start = time.monotonic()
        log_event("HEALTH_CHECK", {"params": params}, level=logging.DEBUG)
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
            resp = await self._request_async("GET", "/health", headers=headers)
            response_headers = list(resp.headers.items())
            body = resp.text
        except httpx.HTTPError as exc:  # pragma: no cover - network errors
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
                "status": resp.status_code,
                "headers": response_headers,
                "body": body,
            },
        )

        if resp.status_code == 200:
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
                log_event(
                    "HEALTH_RESULT",
                    {"ok": True},
                    start_time=start,
                    level=logging.DEBUG,
                )
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
        code = ErrorCode.UNAUTHORIZED if resp.status_code in {401, 403} else ErrorCode.INTERNAL
        message = _("MCP server health check failed")
        details: dict[str, Any] = {"status": resp.status_code, **params}
        if data:
            details["response"] = data
        error = mcp_error(code, message, details)["error"]
        log_event("HEALTH_RESULT", {"error": error}, start_time=start)
        self._update_ready_state(False, error)
        raise MCPNotReadyError(error)

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

