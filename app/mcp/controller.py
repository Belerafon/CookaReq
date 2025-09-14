"""Service controller for managing the MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from http.client import HTTPConnection

from .server import start_server, stop_server, is_running as server_is_running
from ..settings import MCPSettings


class MCPStatus(str, Enum):
    """Status values returned by :class:`MCPController`."""

    NOT_RUNNING = "not running"
    READY = "ready"
    ERROR = "error"



@dataclass
class MCPCheckResult:
    """Detailed result of :meth:`MCPController.check`."""

    status: MCPStatus
    message: str


class MCPController:
    """Service layer controlling the MCP server."""

    def start(self, settings: MCPSettings) -> None:
        """Launch the MCP server with ``settings``."""

        token = settings.token if settings.require_token else ""
        start_server(settings.host, settings.port, settings.base_path, token)

    def stop(self) -> None:
        """Shut down the MCP server if running."""

        stop_server()

    def is_running(self) -> bool:
        """Return ``True`` if MCP server is currently running."""

        return server_is_running()

    def check(self, settings: MCPSettings) -> MCPCheckResult:
        """Probe the MCP server health endpoint."""

        headers = {}
        if settings.require_token and settings.token:
            headers["Authorization"] = f"Bearer {settings.token}"
        try:
            conn = HTTPConnection(settings.host, settings.port, timeout=2)
            try:
                conn.request("GET", "/health", headers=headers)
                resp = conn.getresponse()
                resp.read()
                if resp.status == 200:
                    msg = "GET /health -> 200"
                    return MCPCheckResult(MCPStatus.READY, msg)
                msg = f"GET /health -> {resp.status}"
                return MCPCheckResult(MCPStatus.ERROR, msg)
            finally:
                conn.close()
        except Exception as exc:
            msg = f"connection error: {exc}"
            return MCPCheckResult(MCPStatus.NOT_RUNNING, msg)
