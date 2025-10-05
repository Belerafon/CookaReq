"""Debug logging helpers for agent chat history instrumentation."""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from ...util.time import utc_now_iso


LOGGER_NAMESPACE = "cookareq.ui.agent_chat_panel"
_HISTORY_DEBUG_EVENT = "AGENT_CHAT_HISTORY_TIMING"
_ALLOWED_PHASE_PREFIXES = ("segment_view.render.",)


def get_history_logger(component: str | None = None) -> logging.Logger:
    """Return a logger bound to the agent chat panel namespace."""

    if component:
        return logging.getLogger(f"{LOGGER_NAMESPACE}.{component}")
    return logging.getLogger(LOGGER_NAMESPACE)


def emit_history_debug(
    logger: logging.Logger,
    phase: str,
    /,
    **fields: Any,
) -> None:
    """Emit a structured debug log entry for history instrumentation."""

    if not any(phase.startswith(prefix) for prefix in _ALLOWED_PHASE_PREFIXES):
        return
    if not logger.isEnabledFor(logging.DEBUG):
        return
    normalized_fields = _normalize_fields(fields) if fields else {}
    payload: dict[str, Any] = {
        "event": _HISTORY_DEBUG_EVENT,
        "phase": phase,
        "timestamp": utc_now_iso(),
        "monotonic_ns": time.perf_counter_ns(),
        "thread": threading.current_thread().name,
    }
    if normalized_fields:
        payload.update(normalized_fields)
        try:
            summary = json.dumps(
                normalized_fields,
                ensure_ascii=False,
                sort_keys=True,
            )
        except TypeError:
            summary = repr(normalized_fields)
        message = f"agent_chat_history.{phase} {summary}"
    else:
        message = f"agent_chat_history.{phase}"
    logger.debug(message, extra={"json": payload})


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


__all__ = [
    "emit_history_debug",
    "elapsed_ns",
    "get_history_logger",
    "LOGGER_NAMESPACE",
]
