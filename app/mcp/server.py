"""HTTP server utilities for MCP integration.

This module exposes a FastAPI application with an attached Model
Context Protocol (MCP) server. The server is started with `start_server`
which runs uvicorn in a background thread so that the wxPython GUI main
loop remains responsive.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

from ..log import JsonlHandler, configure_logging, logger
from ..util.time import utc_now_iso
from . import tools_read, tools_write
from .utils import ErrorCode, mcp_error, sanitize

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


def _configure_request_logging(log_dir: str | Path) -> None:
    """Attach file handlers for request logging without mutating the global logger."""
    configure_logging()
    # Remove previous request handlers if any from the dedicated logger
    for h in list(request_logger.handlers):
        if getattr(h, "cookareq_request", False):
            request_logger.removeHandler(h)
            h.close()

    log_dir_path = Path(log_dir)
    log_dir_path.mkdir(parents=True, exist_ok=True)

    text_path = log_dir_path / _TEXT_LOG_NAME
    text_handler = logging.FileHandler(text_path)
    text_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s"),
    )
    text_handler.cookareq_request = True
    request_logger.addHandler(text_handler)

    json_path = log_dir_path / _JSONL_LOG_NAME
    json_handler = JsonlHandler(json_path)
    json_handler.cookareq_request = True
    request_logger.addHandler(json_handler)


def _log_request(request: Request, status: int) -> None:
    headers = sanitize(dict(request.headers))
    query = sanitize(dict(request.query_params))
    entry = {
        "timestamp": utc_now_iso(),
        "method": request.method,
        "path": request.url.path,
        "query": query,
        "headers": headers,
        "status": status,
    }
    request_logger.info(
        "%s %s -> %s",
        request.method,
        request.url.path,
        status,
        extra={"json": entry},
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
def get_requirement(rid: str) -> dict:
    """Return a single requirement by identifier."""
    directory = app.state.base_path
    return tools_read.get_requirement(directory, rid)


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
def create_requirement(prefix: str, data: Mapping[str, object]) -> dict:
    """Create a requirement in the configured directory."""
    directory = app.state.base_path
    return tools_write.create_requirement(directory, prefix=prefix, data=data)


@mcp_server.tool()
def patch_requirement(
    rid: str,
    patch: list[dict],
    *,
    rev: int,
) -> dict:
    """Apply JSON Patch to a requirement."""
    directory = app.state.base_path
    return tools_write.patch_requirement(directory, rid, patch, rev=rev)


@mcp_server.tool()
def delete_requirement(rid: str, *, rev: int) -> dict | None:
    """Delete a requirement if revision matches."""
    directory = app.state.base_path
    return tools_write.delete_requirement(directory, rid, rev=rev)


@mcp_server.tool()
def link_requirements(
    *,
    source_rid: str,
    derived_rid: str,
    link_type: str,
    rev: int,
) -> dict:
    """Link one requirement to another."""
    directory = app.state.base_path
    return tools_write.link_requirements(
        directory,
        source_rid=source_rid,
        derived_rid=derived_rid,
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
            mcp_error(ErrorCode.VALIDATION_ERROR, "invalid json"),
            status_code=400,
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
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
            status_code=400,
        )
    return JSONResponse(result)


# Internal state for the background server
_uvicorn_server: uvicorn.Server | None = None
_server_thread: threading.Thread | None = None


def is_running() -> bool:
    """Return ``True`` if the MCP server is currently running."""
    return _uvicorn_server is not None


def start_server(
    host: str = "127.0.0.1",
    port: int = 59362,
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
        logger.info("MCP server stop requested but no server instance is active")
        return

    thread_alive = _server_thread.is_alive() if _server_thread else False
    logger.info(
        "MCP server stop requested (thread_alive=%s)",
        thread_alive,
    )
    start = time.perf_counter()

    _uvicorn_server.should_exit = True
    if hasattr(_uvicorn_server, "force_exit"):
        _uvicorn_server.force_exit = True

    if _server_thread is not None:
        timeout = 5.0
        logger.info(
            "Waiting up to %.1fs for MCP server thread to terminate", timeout
        )
        _server_thread.join(timeout=timeout)
        if _server_thread.is_alive():
            logger.warning(
                "MCP server thread did not exit within %.1fs; continuing shutdown",
                timeout,
            )
        else:
            logger.info("MCP server thread exited cleanly")

    _uvicorn_server = None
    _server_thread = None

    for h in list(request_logger.handlers):
        if getattr(h, "cookareq_request", False):
            request_logger.removeHandler(h)
            h.close()

    elapsed = time.perf_counter() - start
    logger.info("MCP server shutdown cleanup completed in %.3fs", elapsed)
