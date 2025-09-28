"""Logging helpers for LLM interactions."""

from __future__ import annotations

from typing import Any, Mapping

from ..telemetry import log_debug_payload, log_event

__all__ = ["log_request", "log_response"]


def log_request(payload: Mapping[str, Any]) -> None:
    """Record telemetry for an outbound LLM request."""

    log_debug_payload("LLM_REQUEST", payload)
    log_event("LLM_REQUEST", payload)


def log_response(
    payload: Mapping[str, Any], *, start_time: float | None = None, direction: str = "inbound"
) -> None:
    """Record telemetry for an inbound LLM response."""

    log_event("LLM_RESPONSE", payload, start_time=start_time)
    debug_payload = {"direction": direction, **payload}
    log_debug_payload("LLM_RESPONSE", debug_payload)
