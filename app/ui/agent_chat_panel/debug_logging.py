"""Debug logging helpers for agent chat history instrumentation."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from ...util.time import utc_now_iso


_HISTORY_DEBUG_EVENT = "AGENT_CHAT_HISTORY_TIMING"


def emit_history_debug(
    logger: logging.Logger,
    phase: str,
    /,
    **fields: Any,
) -> None:
    """Emit a structured debug log entry for history instrumentation."""

    if not logger.isEnabledFor(logging.DEBUG):
        return
    payload: dict[str, Any] = {
        "event": _HISTORY_DEBUG_EVENT,
        "phase": phase,
        "timestamp": utc_now_iso(),
        "monotonic_ns": time.perf_counter_ns(),
        "thread": threading.current_thread().name,
    }
    if fields:
        payload.update(_normalize_fields(fields))
    logger.debug(
        "agent_chat_history.%s", phase,
        extra={"json": payload},
    )


def _normalize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in fields.items():
        normalized[key] = _normalize_value(value)
    return normalized


def _normalize_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _normalize_value(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalize_value(inner) for inner in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_normalize_value(inner) for inner in value)
    return value


def elapsed_ns(start_ns: int | None) -> int | None:
    """Return elapsed nanoseconds for instrumentation helpers."""

    if start_ns is None:
        return None
    return time.perf_counter_ns() - start_ns


__all__ = ["emit_history_debug", "elapsed_ns"]
