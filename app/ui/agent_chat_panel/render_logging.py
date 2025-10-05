"""Shared helpers for agent chat render diagnostics."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping, Sequence
from typing import Any

LOGGER_NAME = "cookareq.ui.agent_chat_panel.render"


def get_render_logger() -> logging.Logger:
    """Return the shared logger used for transcript render diagnostics."""

    return logging.getLogger(LOGGER_NAME)


def perf_counter_ns() -> int:
    """High-resolution monotonic timestamp in nanoseconds."""

    return time.perf_counter_ns()


def emit_render_debug(event: str, /, **payload: Any) -> None:
    """Emit a structured DEBUG message for transcript rendering.

    Parameters
    ----------
    event:
        Logical event name. The logger namespace already scopes messages to the
        agent chat panel, so use short, phase-oriented identifiers such as
        ``"segment_view.render.start"``.
    payload:
        Optional keyword arguments describing the event context. Values are
        normalised to JSON-friendly primitives before logging.
    """

    logger = get_render_logger()
    if not logger.isEnabledFor(logging.DEBUG):
        return

    normalized = {key: _normalize(value) for key, value in payload.items()}
    try:
        message = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        message = str(normalized)
    logger.debug("%s %s", event, message)


def _normalize(value: Any) -> Any:
    """Normalise *value* so it can be serialised to JSON."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _normalize(subvalue) for key, subvalue in value.items()}
    if isinstance(value, set):
        return sorted(_normalize(item) for item in value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


__all__ = ["emit_render_debug", "get_render_logger", "perf_counter_ns", "LOGGER_NAME"]
