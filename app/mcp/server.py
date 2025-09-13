"""HTTP server utilities for MCP integration.

This module exposes a FastAPI application with an attached Model
Context Protocol (MCP) server. The server is started with `start_server`
which runs uvicorn in a background thread so that the wxPython GUI main
loop remains responsive.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import datetime
from typing import Mapping, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
from mcp.server.fastmcp import FastMCP

from app.log import JsonlHandler, configure_logging, logger
from app.mcp.utils import ErrorCode, mcp_error, sanitize
from app.mcp import tools_read, tools_write

# Dedicated logger for MCP request logging so global handlers remain untouched
request_logger = logger.getChild("mcp.requests")

# Public FastAPI application and MCP server instances -----------------------

# FastAPI application that will host the MCP routes.  Additional routes may
# be added by the GUI part of the application if needed.
app = FastAPI()
app.state.expected_token = ""
app.state.log_dir = "."

_TEXT_LOG_NAME = "server.log"
_JSONL_LOG_NAME = "server.jsonl"


def _configure_request_logging(log_dir: str) -> None:
    """Attach file handlers for request logging without mutating the global logger."""
    configure_logging()
    # Remove previous request handlers if any from the dedicated logger
    for h in list(request_logger.handlers):
        if getattr(h, "_cookareq_request", False):
            request_logger.removeHandler(h)
            h.close()

    os.makedirs(log_dir, exist_ok=True)

    text_path = os.path.join(log_dir, _TEXT_LOG_NAME)
    text_handler = logging.FileHandler(text_path)
    text_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    text_handler._cookareq_request = True
    request_logger.addHandler(text_handler)

    json_path = os.path.join(log_dir, _JSONL_LOG_NAME)
    json_handler = JsonlHandler(json_path)
    json_handler._cookareq_request = True
    request_logger.addHandler(json_handler)


def _log_request(request: Request, status: int) -> None:
    headers = sanitize(dict(request.headers))
    query = sanitize(dict(request.query_params))
    entry = {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "method": request.method,
        "path": request.url.path,
        "query": query,
        "headers": headers,
        "status": status,
    }
    request_logger.info(
        "%s %s -> %s", request.method, request.url.path, status, extra={"json": entry}
    )


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Validate Authorization header and log every request."""
    token = app.state.expected_token
    if token:
        header = request.headers.get("Authorization")
        if header != f"Bearer {token}":
            response = JSONResponse(
                mcp_error(ErrorCode.UNAUTHORIZED, "unauthorized"),
                status_code=401,
            )
            _log_request(request, response.status_code)
            return response
    response = await call_next(request)
    _log_request(request, response.status_code)
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    """Simple readiness probe used by external tools."""
    return {"status": "ok"}

# FastMCP provides the server-side implementation of the MCP protocol.
# Tools are registered via decorators below and invoked through the custom
# `/mcp` HTTP endpoint defined later in this module.
mcp_server = FastMCP(name="CookaReq")


# ----------------------------- MCP Tools -----------------------------------


@mcp_server.tool()
def list_requirements(
    *,
    page: int = 1,
    per_page: int = 50,
    status: str | None = None,
    labels: list[str] | None = None,
) -> dict:
    """List requirements using the configured base directory."""
    directory = app.state.base_path
    return tools_read.list_requirements(
        directory,
        page=page,
        per_page=per_page,
        status=status,
        labels=labels,
    )


@mcp_server.tool()
def get_requirement(req_id: int) -> dict:
    """Return a single requirement by identifier."""
    directory = app.state.base_path
    return tools_read.get_requirement(directory, req_id)


@mcp_server.tool()
def search_requirements(
    *,
    query: str | None = None,
    labels: list[str] | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Search requirements with optional filters."""
    directory = app.state.base_path
    return tools_read.search_requirements(
        directory,
        query=query,
        labels=labels,
        status=status,
        page=page,
        per_page=per_page,
    )


@mcp_server.tool()
def create_requirement(data: Mapping[str, object]) -> dict:
    """Create a requirement in the configured directory."""
    directory = app.state.base_path
    return tools_write.create_requirement(directory, data)


@mcp_server.tool()
def patch_requirement(
    req_id: int,
    patch: list[dict],
    *,
    rev: int,
) -> dict:
    """Apply JSON Patch to a requirement."""
    directory = app.state.base_path
    return tools_write.patch_requirement(directory, req_id, patch, rev=rev)


@mcp_server.tool()
def delete_requirement(req_id: int, *, rev: int) -> dict | None:
    """Delete a requirement if revision matches."""
    directory = app.state.base_path
    return tools_write.delete_requirement(directory, req_id, rev=rev)


@mcp_server.tool()
def link_requirements(
    *,
    source_id: int,
    derived_id: int,
    link_type: str,
    rev: int,
) -> dict:
    """Link one requirement to another."""
    directory = app.state.base_path
    return tools_write.link_requirements(
        directory,
        source_id=source_id,
        derived_id=derived_id,
        link_type=link_type,
        rev=rev,
    )


# Mapping of tool names to wrapper functions for direct dispatch
_TOOLS: dict[str, callable] = {
    "list_requirements": list_requirements,
    "get_requirement": get_requirement,
    "search_requirements": search_requirements,
    "create_requirement": create_requirement,
    "patch_requirement": patch_requirement,
    "delete_requirement": delete_requirement,
    "link_requirements": link_requirements,
}


# --------------------------- MCP endpoint ----------------------------------


@app.post("/mcp")
async def call_tool(request: Request) -> JSONResponse:
    """Invoke a registered MCP tool via HTTP."""
    try:
        body = await request.json()
    except Exception:  # pragma: no cover - defensive
        return JSONResponse(
            mcp_error(ErrorCode.VALIDATION_ERROR, "invalid json"), status_code=400
        )

    name = body.get("name")
    arguments = body.get("arguments") or {}
    if not isinstance(name, str):
        return JSONResponse(
            mcp_error(ErrorCode.VALIDATION_ERROR, "missing tool name"),
            status_code=400,
        )

    func = _TOOLS.get(name)
    if func is None:
        return JSONResponse(
            mcp_error(ErrorCode.NOT_FOUND, f"unknown tool: {name}"),
            status_code=404,
        )

    try:
        result = func(**arguments)
    except TypeError as exc:
        return JSONResponse(
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)), status_code=400
        )
    return JSONResponse(result)

# Internal state for the background server
_uvicorn_server: Optional[uvicorn.Server] = None
_server_thread: Optional[threading.Thread] = None


def is_running() -> bool:
    """Return ``True`` if the MCP server is currently running."""
    return _uvicorn_server is not None


def start_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    base_path: str = "",
    token: str = "",
) -> None:
    """Start the HTTP server in a background thread.

    Args:
        host: Interface to bind the server to.
        port: TCP port where the server listens.
        base_path: Base filesystem path available to the MCP server.
        token: Authorization token expected in the ``Authorization`` header.
    """
    global _uvicorn_server, _server_thread

    if _uvicorn_server is not None:
        # Server already running
        return

    log_dir = base_path or "."
    app.state.base_path = base_path
    app.state.expected_token = token
    app.state.log_dir = log_dir
    _configure_request_logging(log_dir)
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

    for h in list(request_logger.handlers):
        if getattr(h, "_cookareq_request", False):
            request_logger.removeHandler(h)
            h.close()
