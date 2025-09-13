from __future__ import annotations

import datetime
import json
import time
from typing import Any, Mapping

from app.log import logger

# Keys that should be redacted when logging
SENSITIVE_KEYS = {
    "authorization",
    "token",
    "secret",
    "password",
    "api_key",
    "cookie",
}

REDACTED = "[REDACTED]"


def sanitize(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of *data* with sensitive keys replaced by ``[REDACTED]``."""

    sanitized: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in SENSITIVE_KEYS:
            sanitized[key] = REDACTED
        else:
            sanitized[key] = value
    return sanitized


def log_event(
    event: str,
    payload: Mapping[str, Any] | None = None,
    *,
    start_time: float | None = None,
) -> None:
    """Log an event to the application logger.

    Parameters
    ----------
    event:
        The event type, e.g. ``"LLM_REQUEST"``.
    payload:
        Structured data associated with the event. Sensitive keys are redacted
        automatically.
    start_time:
        Optional monotonic start time; if provided the elapsed time in
        milliseconds is included in the log entry.
    """

    data: dict[str, Any] = {"event": event}
    if payload:
        sanitized = sanitize(dict(payload))
        data["payload"] = sanitized
        data["size_bytes"] = len(json.dumps(sanitized, ensure_ascii=False).encode("utf-8"))
    else:
        data["payload"] = {}
        data["size_bytes"] = 0
    if start_time is not None:
        data["duration_ms"] = int((time.monotonic() - start_time) * 1000)
    logger.info(event, extra={"json": data})
