from __future__ import annotations

from enum import Enum
from http.client import HTTPConnection

from .server import start_server, stop_server, is_running as server_is_running
from ..settings import MCPSettings


class MCPStatus(str, Enum):
    """Status values returned by :class:`MCPController`."""

    NOT_RUNNING = "not running"
    READY = "ready"
    ERROR = "error"


class MCPController:
    """Service layer controlling the MCP server."""

    def start(self, settings: MCPSettings) -> None:
        token = settings.token if settings.require_token else ""
        start_server(settings.host, settings.port, settings.base_path, token)

    def stop(self) -> None:
        stop_server()

    def is_running(self) -> bool:
        return server_is_running()

    def check(self, settings: MCPSettings) -> MCPStatus:
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
                    return MCPStatus.READY
                return MCPStatus.ERROR
            finally:
                conn.close()
        except Exception:
            return MCPStatus.NOT_RUNNING
