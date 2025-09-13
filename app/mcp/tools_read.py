"""Utility functions for MCP requirement access."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from app.core import requirements as req_ops
from app.core.model import Requirement, requirement_to_dict
from app.mcp.utils import ErrorCode, log_tool, mcp_error


def _paginate(requirements: Sequence[Requirement], page: int, per_page: int) -> dict:
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 1
    total = len(requirements)
    start = (page - 1) * per_page
    end = start + per_page
    items = [requirement_to_dict(r) for r in requirements[start:end]]
    return {"total": total, "page": page, "per_page": per_page, "items": items}


def list_requirements(
    directory: str | Path,
    *,
    page: int = 1,
    per_page: int = 50,
    status: str | None = None,
    labels: Sequence[str] | None = None,
) -> dict:
    """Return requirements from ``directory`` with optional filters."""
    params = {
        "directory": str(directory),
        "page": page,
        "per_page": per_page,
        "status": status,
        "labels": list(labels) if labels else None,
    }
    try:
        reqs = req_ops.search_requirements(directory, labels=labels, status=status)
    except FileNotFoundError:
        return log_tool(
            "list_requirements",
            params,
            mcp_error(ErrorCode.NOT_FOUND, "directory not found", {"directory": str(directory)}),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "list_requirements", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    return log_tool("list_requirements", params, _paginate(reqs, page, per_page))


def get_requirement(directory: str | Path, req_id: int) -> dict:
    """Return requirement ``req_id`` from ``directory``."""
    params = {"directory": str(directory), "req_id": req_id}
    try:
        req = req_ops.get_requirement(directory, req_id)
    except FileNotFoundError:
        return log_tool(
            "get_requirement",
            params,
            mcp_error(ErrorCode.NOT_FOUND, f"requirement {req_id} not found"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "get_requirement", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    return log_tool("get_requirement", params, requirement_to_dict(req))


def search_requirements(
    directory: str | Path,
    *,
    query: str | None = None,
    labels: Sequence[str] | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Search requirements with text query and optional filters."""
    params = {
        "directory": str(directory),
        "query": query,
        "labels": list(labels) if labels else None,
        "status": status,
        "page": page,
        "per_page": per_page,
    }
    try:
        reqs = req_ops.search_requirements(
            directory, query=query, labels=labels, status=status
        )
    except FileNotFoundError:
        return log_tool(
            "search_requirements",
            params,
            mcp_error(ErrorCode.NOT_FOUND, "directory not found", {"directory": str(directory)}),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "search_requirements", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    return log_tool("search_requirements", params, _paginate(reqs, page, per_page))
