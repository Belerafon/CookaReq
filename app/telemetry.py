"""Structured telemetry logging helpers."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any

from .log import logger
from .util.json import make_json_safe

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


def _sanitize_value(value: Any) -> Any:
    """Recursively sanitize ``value``."""

    if isinstance(value, Mapping):
        return {
            k: (REDACTED if k.lower() in SENSITIVE_KEYS else _sanitize_value(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_value(v) for v in value)
    return value


def sanitize(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep copy of *data* with sensitive keys replaced by ``[REDACTED]``."""

    return _sanitize_value(dict(data))


def log_event(
    event: str,
    payload: Mapping[str, Any] | None = None,
    *,
    start_time: float | None = None,
    level: int = logging.INFO,
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
    level:
        Logging level used for the emitted record. Defaults to ``logging.INFO``.
    """

    data: dict[str, Any] = {"event": event}
    if payload:
        sanitized = sanitize(dict(payload))
        safe_payload = make_json_safe(sanitized)
        data["payload"] = safe_payload
        data["size_bytes"] = len(
            json.dumps(safe_payload, ensure_ascii=False).encode("utf-8"),
        )
    else:
        data["payload"] = {}
        data["size_bytes"] = 0
    if start_time is not None:
        data["duration_ms"] = int((time.monotonic() - start_time) * 1000)
    logger.log(level, event, extra={"json": data})


def log_debug_payload(
    event: str,
    payload: Mapping[str, Any] | Sequence[Any] | str | None = None,
) -> None:
    """Emit debug-level log entry with full payload details."""

    if not logger.isEnabledFor(logging.DEBUG):
        return

    record: dict[str, Any] = {"event": event, "level": "DEBUG"}
    if payload is None:
        safe_payload: Any = {}
    elif isinstance(payload, Mapping):
        safe_payload = make_json_safe(sanitize(dict(payload)))
    elif isinstance(payload, Sequence) and not isinstance(
        payload, (str, bytes, bytearray)
    ):
        safe_payload = make_json_safe(_sanitize_value(list(payload)))
    else:
        safe_payload = make_json_safe(payload)
    if payload is not None:
        record["payload"] = safe_payload
    message = event
    if payload is not None:
        message = f"{event} {json.dumps(safe_payload, ensure_ascii=False)}"
    logger.debug(message, extra={"json": record})
