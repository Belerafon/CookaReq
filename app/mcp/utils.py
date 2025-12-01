"""Shared helpers for MCP tools."""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from enum import Enum
from json import JSONDecodeError
from typing import Any

from ..log import logger
from ..telemetry import sanitize
from ..util.time import utc_now_iso

try:  # pragma: no cover - optional dependency guards
    import httpx
except Exception:  # pragma: no cover - httpx should be available, keep fallback
    _HTTPX_ERRORS: tuple[type[BaseException], ...] = ()
else:  # pragma: no cover - exercised implicitly when httpx is installed
    _HTTPX_ERRORS = (httpx.HTTPError,)

try:  # pragma: no cover - OpenAI is an optional runtime dependency in tests
    import openai
except Exception:  # pragma: no cover - mirror behaviour when OpenAI isn't installed
    _OPENAI_CONNECTION_ERRORS: tuple[type[BaseException], ...] = ()
    _OPENAI_STATUS_ERROR: tuple[type[BaseException], ...] = ()
    _OPENAI_BASE_ERRORS: tuple[type[BaseException], ...] = ()
else:  # pragma: no cover - executed in production/runtime environment
    _OPENAI_CONNECTION_ERRORS = tuple(
        getattr(openai, name)
        for name in ("APIConnectionError", "APITimeoutError")
        if hasattr(openai, name)
    )
    if hasattr(openai, "APIStatusError"):
        _OPENAI_STATUS_ERROR = (openai.APIStatusError,)
    else:
        _OPENAI_STATUS_ERROR = ()
    if hasattr(openai, "OpenAIError"):
        _OPENAI_BASE_ERRORS = (openai.OpenAIError,)
    else:
        _OPENAI_BASE_ERRORS = ()

_GENERIC_NETWORK_ERRORS: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError)


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
        "timestamp": utc_now_iso(),
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


def mcp_error(
    code: ErrorCode | str,
    message: str,
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a structured error payload for MCP responses."""
    code_str = code.value if isinstance(code, ErrorCode) else str(code)
    err: dict[str, Any] = {"code": code_str, "message": message}
    if details:
        err["details"] = dict(details)
    return {"error": err}


def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """Yield *exc* and all linked exceptions from ``__cause__``/``__context__``."""
    seen: set[int] = set()
    queue: list[BaseException | None] = [exc]
    while queue:
        current = queue.pop()
        if current is None:
            continue
        ident = id(current)
        if ident in seen:
            continue
        seen.add(ident)
        yield current
        queue.append(getattr(current, "__cause__", None))
        queue.append(getattr(current, "__context__", None))


def map_exception_to_error_code(exc: BaseException) -> ErrorCode:
    """Map arbitrary exceptions to standardized :class:`ErrorCode` values.

    The heuristics prioritise user input issues (e.g. JSON parsing errors) over
    infrastructure problems.  Network failures originating from the OpenAI
    client, low-level HTTP stack or built-in connection exceptions are treated
    as :class:`ErrorCode.INTERNAL`, signalling that retrying later might help.
    """
    internal_failure = False
    for err in _exception_chain(exc):
        if isinstance(err, JSONDecodeError):
            return ErrorCode.VALIDATION_ERROR
        if _OPENAI_CONNECTION_ERRORS and isinstance(err, _OPENAI_CONNECTION_ERRORS):
            return ErrorCode.INTERNAL
        if _OPENAI_STATUS_ERROR and isinstance(err, _OPENAI_STATUS_ERROR):
            status = getattr(err, "status_code", None)
            if isinstance(status, int):
                if status == 429 or status >= 500:
                    return ErrorCode.INTERNAL
                if 400 <= status < 500:
                    return ErrorCode.VALIDATION_ERROR
            internal_failure = True
            continue
        if _HTTPX_ERRORS and isinstance(err, _HTTPX_ERRORS):
            internal_failure = True
            continue
        if isinstance(err, _GENERIC_NETWORK_ERRORS):
            internal_failure = True
            continue
        if _OPENAI_BASE_ERRORS and isinstance(err, _OPENAI_BASE_ERRORS):
            internal_failure = True
    return ErrorCode.INTERNAL if internal_failure else ErrorCode.VALIDATION_ERROR


def exception_to_mcp_error(exc: BaseException) -> dict[str, Any]:
    """Convert *exc* into an MCP-compatible error payload."""
    code = map_exception_to_error_code(exc)
    message = str(exc) or type(exc).__name__
    details: dict[str, Any] = {"type": type(exc).__name__}
    llm_message = getattr(exc, "llm_message", None)
    if llm_message is not None:
        details["llm_message"] = str(llm_message)
    llm_tool_calls = getattr(exc, "llm_tool_calls", None)
    if llm_tool_calls:
        serialized_calls: list[Any] = []
        for call in llm_tool_calls:
            if isinstance(call, Mapping):
                serialized_calls.append(dict(call))
            else:
                serialized_calls.append(call)
        details["llm_tool_calls"] = serialized_calls
    llm_request_messages = getattr(exc, "llm_request_messages", None)
    if llm_request_messages:
        serialized_messages: list[Any] = []
        for raw_message in llm_request_messages:
            if isinstance(raw_message, Mapping):
                serialized_messages.append(dict(raw_message))
            else:
                serialized_messages.append(raw_message)
        details["llm_request_messages"] = serialized_messages
    llm_reasoning = getattr(exc, "llm_reasoning", None)
    if llm_reasoning:
        serialized_reasoning: list[Any] = []
        for segment in llm_reasoning:
            if isinstance(segment, Mapping):
                serialized_reasoning.append(dict(segment))
            else:
                serialized_reasoning.append(segment)
        details["llm_reasoning"] = serialized_reasoning
    llm_response_summary = getattr(exc, "llm_response_summary", None)
    if llm_response_summary:
        details["llm_response_summary"] = str(llm_response_summary)
    tool_results = getattr(exc, "tool_results", None)
    if tool_results:
        serialized_results: list[Any] = []
        for result in tool_results:
            if isinstance(result, Mapping):
                serialized_results.append(dict(result))
            else:
                serialized_results.append(result)
        details["tool_results"] = serialized_results
    return mcp_error(code, message, details)
