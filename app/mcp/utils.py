from __future__ import annotations

from enum import Enum
from typing import Any, Mapping


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
