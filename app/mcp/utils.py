"""Shared helpers for MCP tools."""

from __future__ import annotations

import datetime
from enum import Enum
from typing import Any, Mapping

from app.log import logger
from app.telemetry import sanitize


def log_tool(
    tool: str,
    params: Mapping[str, Any],
    result: Any,
    *,
    max_result_length: int | None = 1000,
) -> Any:
    """Log tool invocation in JSONL and return *result*.

    Parameters
    ----------
    tool:
        Name of the tool being invoked.
    params:
        Parameters passed to the tool; sensitive keys are redacted.
    result:
        Result returned by the tool.  If *max_result_length* is set and the
        textual representation of the result exceeds this limit it will be
        truncated with an ellipsis in the log entry.  The original *result* is
        still returned unmodified.
    max_result_length:
        Maximum number of characters from the result to include in the log.
        ``None`` disables truncation.
    """

    entry = {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "tool": tool,
        "params": sanitize(params),
    }
    if isinstance(result, dict) and "error" in result:
        entry["error"] = result["error"]
    else:
        entry["result"] = result

    if max_result_length is not None and "result" in entry:
        res = entry["result"]
        if isinstance(res, str) and len(res) > max_result_length:
            entry["result"] = res[:max_result_length] + "..."

    logger.info("tool %s", tool, extra={"json": entry})
    return result


class ErrorCode(str, Enum):
    """Standardized error codes for MCP tools."""

    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONFLICT = "CONFLICT"
    NOT_FOUND = "NOT_FOUND"
    UNAUTHORIZED = "UNAUTHORIZED"
    INTERNAL = "INTERNAL"


def mcp_error(code: ErrorCode | str, message: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a structured error payload for MCP responses."""

    code_str = code.value if isinstance(code, ErrorCode) else str(code)
    err: dict[str, Any] = {"code": code_str, "message": message}
    if details:
        err["details"] = dict(details)
    return {"error": err}
