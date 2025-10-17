"""MCP tool helpers for user-provided documentation files."""
from __future__ import annotations

from typing import Any

from ..services.user_documents import UserDocumentsService, normalise_text_encoding
from .utils import ErrorCode, log_tool, mcp_error


def _missing_root_error(tool: str, params: dict[str, Any]) -> dict[str, Any]:
    return log_tool(
        tool,
        params,
        mcp_error(ErrorCode.NOT_FOUND, "documents root not configured"),
    )
def list_user_documents(service: UserDocumentsService | None) -> dict[str, Any]:
    """Return a serialized tree of available user documents."""
    params: dict[str, Any] = {}
    if service is None:
        return _missing_root_error("list_user_documents", params)
    params["root"] = str(service.root)
    try:
        payload = service.list_tree()
    except RuntimeError as exc:
        return log_tool(
            "list_user_documents",
            params,
            mcp_error(ErrorCode.INTERNAL, str(exc) or "failed to list documents"),
        )
    return log_tool("list_user_documents", params, payload)


def read_user_document(
    service: UserDocumentsService | None,
    path: str,
    *,
    start_line: int = 1,
    max_bytes: int | None = None,
) -> dict[str, Any]:
    """Read the requested document while enforcing configured limits."""
    params: dict[str, Any] = {"path": path, "start_line": start_line}
    if max_bytes is not None:
        params["max_bytes"] = max_bytes
    if service is None:
        return _missing_root_error("read_user_document", params)
    try:
        payload = service.read_file(path, start_line=start_line, max_bytes=max_bytes)
    except FileNotFoundError:
        return log_tool(
            "read_user_document",
            params,
            mcp_error(ErrorCode.NOT_FOUND, "file not found", {"path": path}),
        )
    except IsADirectoryError:
        return log_tool(
            "read_user_document",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, "path points to a directory"),
        )
    except PermissionError:
        return log_tool(
            "read_user_document",
            params,
            mcp_error(ErrorCode.UNAUTHORIZED, "access outside documents root denied"),
        )
    except ValueError as exc:
        return log_tool(
            "read_user_document",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc) or "invalid arguments"),
        )
    if payload.get("clamped_to_limit"):
        requested = payload.get("bytes_requested")
        consumed = payload.get("bytes_consumed")
        remaining = payload.get("bytes_remaining")
        end_line = payload.get("end_line")
        limit = service.max_read_bytes
        mid_line = bool(payload.get("truncated_mid_line"))
        next_line = start_line
        if isinstance(end_line, int) and end_line >= start_line:
            next_line = end_line + 1
        remaining_int = int(remaining) if isinstance(remaining, int) else 0
        requested_int = int(requested) if isinstance(requested, int) else limit
        consumed_int = int(consumed) if isinstance(consumed, int) else 0
        message_parts: list[str] = [
            (
                f"Served {consumed_int} bytes out of the {requested_int} requested."
            ),
            f"{limit} bytes is the maximum chunk size per call.",
        ]
        continuation: dict[str, Any] = {
            "bytes_remaining": remaining_int,
            "next_start_line": next_line,
            "max_chunk_bytes": limit,
            "truncated_mid_line": mid_line,
        }
        if mid_line:
            continuation["line_exceeded_chunk_limit"] = True
        if remaining_int > 0:
            if mid_line:
                message_parts.append(
                    "The last displayed line was cut mid-way because it exceeds"
                    " the per-call byte limit. Raising the limit is required to"
                    " capture the remainder of that line."
                )
            message_parts.append(
                "Continue by calling `read_user_document` with "
                f"`start_line={next_line}` and `max_bytes<={limit}`."
            )
            continuation["suggested_call"] = {
                "name": "read_user_document",
                "arguments": {
                    "path": path,
                    "start_line": next_line,
                    "max_bytes": limit,
                },
            }
            message_parts.append(
                f"Approximately {remaining_int} bytes remain after this chunk."
            )
        else:
            if mid_line:
                message_parts.append(
                    "The file ended inside the partially displayed line."
                )
            else:
                message_parts.append(
                    "The file ended within this chunk; no additional data remains."
                )
        message = " ".join(message_parts)
        payload["notice"] = message
        payload["continuation_hint"] = continuation
    return log_tool("read_user_document", params, payload)


def create_user_document(
    service: UserDocumentsService | None,
    path: str,
    *,
    content: str = "",
    exist_ok: bool = False,
    encoding: str | None = None,
) -> dict[str, Any]:
    """Persist a document under the configured root, optionally replacing it."""
    params: dict[str, Any] = {
        "path": path,
        "exist_ok": exist_ok,
    }
    if encoding is not None:
        params["encoding"] = encoding
    if service is None:
        return _missing_root_error("create_user_document", params)
    try:
        normalized_encoding = normalise_text_encoding(encoding)
        encoded_bytes = content.encode(normalized_encoding)
        created = service.create_file(
            path,
            content=content,
            exist_ok=exist_ok,
            encoding=normalized_encoding,
        )
    except FileExistsError:
        return log_tool(
            "create_user_document",
            params,
            mcp_error(ErrorCode.CONFLICT, "file already exists"),
        )
    except IsADirectoryError:
        return log_tool(
            "create_user_document",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, "path refers to a directory"),
        )
    except PermissionError:
        return log_tool(
            "create_user_document",
            params,
            mcp_error(ErrorCode.UNAUTHORIZED, "access outside documents root denied"),
        )
    except LookupError as exc:
        return log_tool(
            "create_user_document",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except UnicodeEncodeError as exc:
        return log_tool(
            "create_user_document",
            params,
            mcp_error(
                ErrorCode.VALIDATION_ERROR,
                f"content cannot be encoded with {normalized_encoding}: {exc.reason}",
            ),
        )
    payload = {
        "path": created.relative_to(service.root).as_posix(),
        "bytes_written": len(encoded_bytes),
        "encoding": normalized_encoding,
    }
    return log_tool("create_user_document", params, payload)


def delete_user_document(
    service: UserDocumentsService | None,
    path: str,
) -> dict[str, Any]:
    """Remove the specified document from the managed root."""
    params: dict[str, Any] = {"path": path}
    if service is None:
        return _missing_root_error("delete_user_document", params)
    try:
        service.delete_file(path)
    except FileNotFoundError:
        return log_tool(
            "delete_user_document",
            params,
            mcp_error(ErrorCode.NOT_FOUND, "file not found", {"path": path}),
        )
    except IsADirectoryError:
        return log_tool(
            "delete_user_document",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, "path refers to a directory"),
        )
    except PermissionError:
        return log_tool(
            "delete_user_document",
            params,
            mcp_error(ErrorCode.UNAUTHORIZED, "access outside documents root denied"),
        )
    payload = {"path": path, "deleted": True}
    return log_tool("delete_user_document", params, payload)
