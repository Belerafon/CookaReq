"""MCP tool helpers for user-provided documentation files."""

from __future__ import annotations

from typing import Any

from ..services.user_documents import UserDocumentsService
from .utils import ErrorCode, log_tool, mcp_error


def _missing_root_error(tool: str, params: dict[str, Any]) -> dict[str, Any]:
    return log_tool(
        tool,
        params,
        mcp_error(ErrorCode.NOT_FOUND, "documents root not configured"),
    )


def _normalize_max_bytes(service: UserDocumentsService, value: int | None) -> int:
    limit = service.max_read_bytes
    if value is None:
        return limit
    if value <= 0:
        raise ValueError("max_bytes must be greater than zero")
    if value > limit:
        raise ValueError(
            f"max_bytes must not exceed {limit} bytes",
        )
    return value


def list_user_documents(service: UserDocumentsService | None) -> dict[str, Any]:
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
    params: dict[str, Any] = {"path": path, "start_line": start_line}
    if max_bytes is not None:
        params["max_bytes"] = max_bytes
    if service is None:
        return _missing_root_error("read_user_document", params)
    try:
        resolved_max = _normalize_max_bytes(service, max_bytes)
        payload = service.read_file(path, start_line=start_line, max_bytes=resolved_max)
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
    return log_tool("read_user_document", params, payload)


def create_user_document(
    service: UserDocumentsService | None,
    path: str,
    *,
    content: str = "",
    exist_ok: bool = False,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "path": path,
        "exist_ok": exist_ok,
        "bytes": len(content.encode("utf-8")),
    }
    if service is None:
        return _missing_root_error("create_user_document", params)
    try:
        created = service.create_file(path, content=content, exist_ok=exist_ok)
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
    payload = {
        "path": created.relative_to(service.root).as_posix(),
        "bytes_written": len(content.encode("utf-8")),
    }
    return log_tool("create_user_document", params, payload)


def delete_user_document(
    service: UserDocumentsService | None,
    path: str,
) -> dict[str, Any]:
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
