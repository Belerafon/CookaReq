"""HTTP server utilities for MCP integration.

This module exposes a FastAPI application with an attached Model
Context Protocol (MCP) server. The server is started with `start_server`
which runs uvicorn in a background thread so that the wxPython GUI main
loop remains responsive.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any
from uuid import uuid4


import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..log import JsonlHandler, logger
from ..services.requirements import RequirementsService
from ..services.user_documents import (
    MAX_ALLOWED_READ_BYTES,
    UserDocumentsService,
)
from ..util.time import utc_now_iso
from .paths import resolve_documents_root
from . import request_logging
from .service_cache import RequirementsServiceCache
from .tool_registry import build_tool_registry
from .utils import ErrorCode, exception_to_mcp_error, mcp_error, sanitize

_REQUEST_LOG_MAX_BYTES = request_logging._REQUEST_LOG_MAX_BYTES
_REQUEST_BACKUP_COUNT = request_logging._REQUEST_BACKUP_COUNT
request_logger = request_logging.request_logger

# Public FastAPI application and MCP server instances -----------------------

# FastAPI application that will host the MCP routes.  Additional routes may
# be added by the GUI part of the application if needed.
app = FastAPI()
app.state.base_path = ""
app.state.expected_token = ""
app.state.log_dir = "."
app.state.max_context_tokens = 0
app.state.token_model = None
app.state.documents_service: UserDocumentsService | None = None
app.state.requirements_service_cache = RequirementsServiceCache()


def get_requirements_service(base_path: str | Path) -> RequirementsService:
    """Return a cached :class:`RequirementsService` for ``base_path``."""
    cache: RequirementsServiceCache = app.state.requirements_service_cache
    return cache.get(base_path)




def _configure_request_logging(log_dir: str | Path | None) -> Path:
    """Compatibility wrapper for request log setup used by tests."""
    request_logging._REQUEST_LOG_MAX_BYTES = _REQUEST_LOG_MAX_BYTES
    request_logging._REQUEST_BACKUP_COUNT = _REQUEST_BACKUP_COUNT
    return request_logging.configure_request_logging(log_dir)


def _log_request(
    request: Request,
    status: int,
    *,
    duration_ms: float | None = None,
    error: str | None = None,
) -> None:
    """Compatibility wrapper for request log emission used internally."""
    request_logging.log_request(
        request,
        status,
        duration_ms=duration_ms,
        error=error,
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
    """Report readiness information for external health probes."""
    return {"status": "ok"}


# ----------------------------- MCP Tools -----------------------------------


def _base_path() -> str:
    return str(app.state.base_path)


def _documents_service() -> UserDocumentsService | None:
    return app.state.documents_service


_TOOLS, _TOOL_METADATA = build_tool_registry(
    base_path_provider=_base_path,
    documents_service_provider=_documents_service,
)


# --------------------------- MCP metadata ---------------------------------


@app.get("/mcp/schema")
async def describe_tools() -> dict[str, Any]:
    """Return registered MCP tool schemas for LocalAgent synchronisation."""
    return {
        "tools": {
            name: dict(metadata)
            for name, metadata in sorted(_TOOL_METADATA.items())
        }
    }


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
    request_logging.request_logger.info(
        "tool %s %s",
        name,
        outcome,
        extra={"json": payload},
    )


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
    documents_path: str | Path | None = "share",
    token: str = "",
    *,
    max_context_tokens: int,
    token_model: str | None = None,
    documents_max_read_kb: int = 10,
    log_dir: str | Path | None = None,
) -> None:
    """Start the HTTP server in a background thread.

    Args:
        host: Interface to bind the server to.
        port: TCP port where the server listens.
        base_path: Base filesystem path available to the MCP server.
        documents_path: Directory containing user documentation accessible to
            tools. Relative paths are resolved against ``base_path``.
        token: Authorization token expected in the ``Authorization`` header.
        max_context_tokens: Maximum context window used for percentage
            calculations when reporting document sizes.
        token_model: Identifier of the tokenizer model used for token counts.
        documents_max_read_kb: Maximum number of kilobytes returned by
            ``read_user_document`` when the agent omits ``max_bytes``.
        log_dir: Directory where request logs are stored.  Defaults to the
            application log directory under ``mcp`` when not provided.
    """
    global _uvicorn_server, _server_thread

    if _uvicorn_server is not None:
        # Server already running
        return

    max_read_kb = int(documents_max_read_kb)
    if max_read_kb <= 0:
        raise ValueError("documents_max_read_kb must be positive")
    if max_read_kb * 1024 > MAX_ALLOWED_READ_BYTES:
        raise ValueError(
            "documents_max_read_kb exceeds supported limit"
            f" ({MAX_ALLOWED_READ_BYTES // 1024} KiB)"
        )

    cache: RequirementsServiceCache = app.state.requirements_service_cache
    cache.activate(base_path)
    app.state.base_path = base_path
    documents_root = resolve_documents_root(base_path, documents_path)
    app.state.documents_root = str(documents_root) if documents_root else None
    app.state.max_context_tokens = int(max_context_tokens)
    app.state.token_model = token_model
    app.state.documents_max_read_bytes = max_read_kb * 1024
    if documents_root is not None:
        app.state.documents_service = UserDocumentsService(
            documents_root,
            max_context_tokens=max_context_tokens,
            token_model=token_model,
            max_read_bytes=app.state.documents_max_read_bytes,
        )
    else:
        app.state.documents_service = None
    app.state.expected_token = token
    resolved_log_dir = _configure_request_logging(log_dir)
    app.state.log_dir = str(resolved_log_dir)
    # Configure logging for frozen environment
    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stderr"
            }
        },
        "formatters": {
            "default": {
                "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            }
        },
        "root": {
            "level": "INFO",
            "handlers": ["default"]
        }
    }
    
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        log_config=log_config
    )
    _uvicorn_server = uvicorn.Server(config)
    # Disable signal handlers so uvicorn can run outside the main thread
    _uvicorn_server.install_signal_handlers = False

    def _run() -> None:
        try:
            _uvicorn_server.run()
        except Exception:  # pragma: no cover - relies on uvicorn internals
            logger.exception("MCP server terminated with an unhandled exception")
            raise

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

    request_logging.close_request_logging_handlers()

    elapsed = time.perf_counter() - start
    logger.info("MCP server shutdown cleanup completed in %.3fs", elapsed)
    app.state.documents_root = None
    app.state.documents_service = None
    app.state.max_context_tokens = 0
    app.state.token_model = None
    app.state.base_path = ""
    cache: RequirementsServiceCache = app.state.requirements_service_cache
    cache.deactivate()
