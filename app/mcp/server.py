"""HTTP server utilities for MCP integration.

This module exposes a FastAPI application with an attached Model
Context Protocol (MCP) server. The server is started with `start_server`
which runs uvicorn in a background thread so that the wxPython GUI main
loop remains responsive.
"""

from __future__ import annotations

import threading
from typing import Optional

from fastapi import FastAPI
import uvicorn
from mcp.server.fastmcp import FastMCP

# Public FastAPI application and MCP server instances -----------------------

# FastAPI application that will host the MCP routes.  Additional routes may
# be added by the GUI part of the application if needed.
app = FastAPI()

# FastMCP provides the server-side implementation of the MCP protocol.
# Using the default configuration is sufficient for exposing an HTTP
# endpoint that tools like the MCP SDK can connect to.
mcp_server = FastMCP(name="CookaReq")

# Mount the MCP Starlette application under the root FastAPI app.  The
# FastMCP instance already defines its own path ("/mcp" by default), so we
# mount it at the root without an extra prefix to avoid double paths.
app.mount("/", mcp_server.streamable_http_app())

# Internal state for the background server
_uvicorn_server: Optional[uvicorn.Server] = None
_server_thread: Optional[threading.Thread] = None


def start_server(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start the HTTP server in a background thread.

    Args:
        host: Interface to bind the server to.
        port: TCP port where the server listens.
    """
    global _uvicorn_server, _server_thread

    if _uvicorn_server is not None:
        # Server already running
        return

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    _uvicorn_server = uvicorn.Server(config)
    # Disable signal handlers so uvicorn can run outside the main thread
    _uvicorn_server.install_signal_handlers = False

    def _run() -> None:
        _uvicorn_server.run()

    _server_thread = threading.Thread(target=_run, daemon=True)
    _server_thread.start()


def stop_server() -> None:
    """Stop the background HTTP server if it is running."""
    global _uvicorn_server, _server_thread

    if _uvicorn_server is None:
        return

    _uvicorn_server.should_exit = True
    if _server_thread is not None:
        _server_thread.join()

    _uvicorn_server = None
    _server_thread = None
