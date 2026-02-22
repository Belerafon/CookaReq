"""Dedicated request logging helpers for MCP HTTP server."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from fastapi import Request

from ..log import (
    JsonlHandler,
    _rotate_if_already_full,
    configure_logging,
    get_log_directory,
    logger,
)
from ..util.time import utc_now_iso
from .utils import sanitize

request_logger = logger.getChild("mcp.requests")
request_logger.setLevel(logging.INFO)
request_logger.propagate = False

_TEXT_LOG_NAME = "server.log"
_JSONL_LOG_NAME = "server.jsonl"
_REQUEST_LOG_MAX_BYTES = 2 * 1024 * 1024
_REQUEST_BACKUP_COUNT = 5


def configure_request_logging(log_dir: str | Path | None) -> Path:
    """Attach request logger handlers and return the resolved log directory."""
    configure_logging()

    for handler in list(request_logger.handlers):
        if getattr(handler, "cookareq_request", False):
            request_logger.removeHandler(handler)
            handler.close()

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


def log_request(
    request: Request,
    status: int,
    *,
    duration_ms: float | None = None,
    error: str | None = None,
) -> None:
    """Emit a structured request log record for a handled HTTP request."""
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


def close_request_logging_handlers() -> None:
    """Detach and close handlers managed by this module."""
    for handler in list(request_logger.handlers):
        if getattr(handler, "cookareq_request", False):
            request_logger.removeHandler(handler)
            handler.close()
