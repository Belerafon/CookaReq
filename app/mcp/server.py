"""HTTP server utilities for MCP integration.

This module exposes a FastAPI application with an attached Model
Context Protocol (MCP) server. The server is started with `start_server`
which runs uvicorn in a background thread so that the wxPython GUI main
loop remains responsive.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..log import (
    JsonlHandler,
    _rotate_if_already_full,
    configure_logging,
    get_log_directory,
    logger,
)
from ..util.time import utc_now_iso
from . import tools_read, tools_write
from .utils import ErrorCode, exception_to_mcp_error, mcp_error, sanitize

# Dedicated logger for MCP request logging so global handlers remain untouched
request_logger = logger.getChild("mcp.requests")
request_logger.setLevel(logging.INFO)
request_logger.propagate = False

# Public FastAPI application and MCP server instances -----------------------

# FastAPI application that will host the MCP routes.  Additional routes may
# be added by the GUI part of the application if needed.
app = FastAPI()
app.state.expected_token = ""
app.state.log_dir = "."

_TEXT_LOG_NAME = "server.log"
_JSONL_LOG_NAME = "server.jsonl"
_REQUEST_LOG_MAX_BYTES = 2 * 1024 * 1024
_REQUEST_BACKUP_COUNT = 5


def _configure_request_logging(log_dir: str | Path | None) -> Path:
    """Attach file handlers for request logging without mutating the global logger."""
    configure_logging()
    # Remove previous request handlers if any from the dedicated logger
    for h in list(request_logger.handlers):
        if getattr(h, "cookareq_request", False):
            request_logger.removeHandler(h)
            h.close()

    if log_dir:
        log_dir_path = Path(log_dir).expanduser()
    else:
        log_dir_path = get_log_directory() / "mcp"
    log_dir_path.mkdir(parents=True, exist_ok=True)

    text_path = log_dir_path / _TEXT_LOG_NAME
    text_size = text_path.stat().st_size if text_path.exists() else 0
    text_handler = RotatingFileHandler(
        text_path,
        encoding="utf-8",
        maxBytes=_REQUEST_LOG_MAX_BYTES,
        backupCount=_REQUEST_BACKUP_COUNT,
    )
    text_handler.setLevel(logging.INFO)
    text_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s"),
    )
    _rotate_if_already_full(text_handler, text_size)
    text_handler.cookareq_request = True
    request_logger.addHandler(text_handler)

    json_path = log_dir_path / _JSONL_LOG_NAME
    json_size = json_path.stat().st_size if json_path.exists() else 0
    json_handler = JsonlHandler(
        json_path,
        backup_count=_REQUEST_BACKUP_COUNT,
    )
    json_handler.setLevel(logging.INFO)
    _rotate_if_already_full(json_handler, json_size)
    json_handler.cookareq_request = True
    request_logger.addHandler(json_handler)
    return log_dir_path


def _log_request(
    request: Request,
    status: int,
    *,
    duration_ms: float | None = None,
    error: str | None = None,
) -> None:
    headers = sanitize(dict(request.headers))
    query = sanitize(dict(request.query_params))
    entry: dict[str, Any] = {
        "timestamp": utc_now_iso(),
        "method": request.method,
        "path": request.url.path,
        "query": query,
        "headers": headers,
        "status": status,
    }
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        entry["request_id"] = request_id
    client = request.client
    if client:
        entry["client"] = {"host": client.host, "port": client.port}
    if duration_ms is not None:
        entry["duration_ms"] = round(duration_ms, 3)
    if error is not None:
        entry["error"] = error
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
    request.state.request_id = uuid4().hex
    start = time.perf_counter()
    token = app.state.expected_token
    if token:
        header = request.headers.get("Authorization")
        if header != f"Bearer {token}":
            response = JSONResponse(
                mcp_error(ErrorCode.UNAUTHORIZED, "unauthorized"),
                status_code=401,
            )
            elapsed = (time.perf_counter() - start) * 1000
            _log_request(request, response.status_code, duration_ms=elapsed)
            return response
    try:
        response = await call_next(request)
    except Exception as exc:  # pragma: no cover - framework guard
        elapsed = (time.perf_counter() - start) * 1000
        error = f"{type(exc).__name__}: {exc}"
        _log_request(request, 500, duration_ms=elapsed, error=error)
        raise
    elapsed = (time.perf_counter() - start) * 1000
    _log_request(request, response.status_code, duration_ms=elapsed)
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    """Simple readiness probe used by external tools."""
    return {"status": "ok"}


# ----------------------------- MCP Tools -----------------------------------

ToolCallable = Callable[..., dict | None]

_TOOLS: dict[str, ToolCallable] = {}


def register_tool(
    func: ToolCallable | None = None,
    *,
    name: str | None = None,
) -> ToolCallable | Callable[[ToolCallable], ToolCallable]:
    """Register *func* in the global tools registry.

    When used as ``@register_tool()`` the tool is stored under ``func.__name__``.
    A custom *name* may be provided via ``@register_tool(name="foo")``.  The
    decorator returns the original function unchanged so regular unit testing
    remains straightforward.
    """

    def decorator(target: ToolCallable) -> ToolCallable:
        tool_name = name or target.__name__
        if tool_name in _TOOLS:
            raise ValueError(f"duplicate MCP tool registered: {tool_name}")
        _TOOLS[tool_name] = target
        return target

    if func is not None:
        return decorator(func)
    return decorator


@register_tool()
def list_requirements(
    *,
    page: int = 1,
    per_page: int = 50,
    status: str | None = None,
    labels: list[str] | None = None,
    fields: list[str] | None = None,
) -> dict:
    """List requirements using the configured base directory."""
    directory = app.state.base_path
    return tools_read.list_requirements(
        directory,
        page=page,
        per_page=per_page,
        status=status,
        labels=labels,
        fields=fields,
    )


@register_tool()
def get_requirement(rid: str, fields: list[str] | None = None) -> dict:
    """Return a single requirement by identifier."""
    directory = app.state.base_path
    return tools_read.get_requirement(directory, rid, fields=fields)


@register_tool()
def search_requirements(
    *,
    query: str | None = None,
    labels: list[str] | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 50,
    fields: list[str] | None = None,
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
        fields=fields,
    )


@register_tool()
def create_requirement(prefix: str, data: Mapping[str, object]) -> dict:
    """Create a requirement in the configured directory."""
    directory = app.state.base_path
    return tools_write.create_requirement(directory, prefix=prefix, data=data)


@register_tool()
def update_requirement_field(rid: str, *, field: str, value: Any) -> dict:
    """Update a single field of a requirement."""
    directory = app.state.base_path
    return tools_write.update_requirement_field(
        directory,
        rid,
        field=field,
        value=value,
    )


@register_tool()
def set_requirement_labels(rid: str, labels: Sequence[str]) -> dict:
    """Replace labels of a requirement."""
    directory = app.state.base_path
    return tools_write.set_requirement_labels(directory, rid, labels)


@register_tool()
def set_requirement_attachments(
    rid: str, attachments: Sequence[Mapping[str, Any]]
) -> dict:
    """Replace attachments of a requirement."""
    directory = app.state.base_path
    return tools_write.set_requirement_attachments(directory, rid, attachments)


@register_tool()
def set_requirement_links(
    rid: str, links: Sequence[Mapping[str, Any] | str]
) -> dict:
    """Replace outgoing links of a requirement."""
    directory = app.state.base_path
    return tools_write.set_requirement_links(directory, rid, links)


@register_tool()
def delete_requirement(rid: str) -> dict | None:
    """Delete a requirement."""
    directory = app.state.base_path
    return tools_write.delete_requirement(directory, rid)


@register_tool()
def link_requirements(
    *,
    source_rid: str,
    derived_rid: str,
    link_type: str,
) -> dict:
    """Link one requirement to another."""
    directory = app.state.base_path
    return tools_write.link_requirements(
        directory,
        source_rid=source_rid,
        derived_rid=derived_rid,
        link_type=link_type,
    )


# --------------------------- MCP endpoint ----------------------------------


@app.post("/mcp")
async def call_tool(request: Request) -> JSONResponse:
    """Invoke a registered MCP tool via HTTP."""
    request_id = getattr(request.state, "request_id", None)
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
        _log_tool_event(
            name,
            arguments,
            "invalid-arguments",
            request_id=request_id,
            error=str(exc),
        )
        return JSONResponse(
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
            status_code=400,
        )
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unhandled MCP tool failure for %s", name)
        error_payload = exception_to_mcp_error(exc)
        _log_tool_event(
            name,
            arguments,
            "error",
            request_id=request_id,
            error=str(exc),
        )
        return JSONResponse(error_payload, status_code=500)
    _log_tool_event(name, arguments, "ok", request_id=request_id)
    return JSONResponse(result)


def _log_tool_event(
    name: str,
    arguments: Mapping[str, Any] | None,
    outcome: str,
    *,
    request_id: str | None,
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "timestamp": utc_now_iso(),
        "tool": name,
        "outcome": outcome,
    }
    if arguments is not None:
        with suppress(Exception):
            payload["arguments"] = sanitize(dict(arguments))
    if request_id:
        payload["request_id"] = request_id
    if error is not None:
        payload["error"] = error
    request_logger.info("tool %s %s", name, outcome, extra={"json": payload})


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
    *,
    log_dir: str | Path | None = None,
) -> None:
    """Start the HTTP server in a background thread.

    Args:
        host: Interface to bind the server to.
        port: TCP port where the server listens.
        base_path: Base filesystem path available to the MCP server.
        token: Authorization token expected in the ``Authorization`` header.
        log_dir: Directory where request logs are stored.  Defaults to the
            application log directory under ``mcp`` when not provided.
    """
    global _uvicorn_server, _server_thread

    if _uvicorn_server is not None:
        # Server already running
        return

    app.state.base_path = base_path
    app.state.expected_token = token
    resolved_log_dir = _configure_request_logging(log_dir)
    app.state.log_dir = str(resolved_log_dir)
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

    if _server_thread is not None:
        timeout = 5.0
        logger.info(
            "Waiting up to %.1fs for MCP server thread to terminate", timeout
        )
        _server_thread.join(timeout=timeout)
        if _server_thread.is_alive():
            logger.warning(
                "MCP server thread did not exit within %.1fs; forcing shutdown",
                timeout,
            )
            if hasattr(_uvicorn_server, "force_exit"):
                try:
                    _uvicorn_server.force_exit = True
                except Exception:  # pragma: no cover - defensive guard
                    logger.exception(
                        "Failed to request uvicorn force-exit during shutdown",
                    )
            extra_wait = 1.0
            _server_thread.join(timeout=extra_wait)
            if _server_thread.is_alive():
                logger.error(
                    "MCP server thread still running after forced shutdown request",
                )
            else:
                logger.info(
                    "MCP server thread exited after forced shutdown request",
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
