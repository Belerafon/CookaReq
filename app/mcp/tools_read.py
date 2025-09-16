from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..core import doc_store
from ..core.model import requirement_to_dict
from .utils import ErrorCode, log_tool, mcp_error


def _page_to_payload(page: doc_store.RequirementPage) -> dict:
    items: list[dict] = []
    for req in page.items:
        data = requirement_to_dict(req)
        data["rid"] = req.rid
        items.append(data)
    return {
        "total": page.total,
        "page": page.page,
        "per_page": page.per_page,
        "items": items,
    }


def list_requirements(
    directory: str | Path,
    *,
    page: int = 1,
    per_page: int = 50,
    status: str | None = None,
    labels: Sequence[str] | None = None,
) -> dict:
    params = {
        "directory": str(directory),
        "page": page,
        "per_page": per_page,
        "status": status,
        "labels": list(labels) if labels else None,
    }
    try:
        page_data = doc_store.list_requirements(
            directory,
            page=page,
            per_page=per_page,
            status=status,
            labels=labels,
        )
    except FileNotFoundError:
        return log_tool(
            "list_requirements",
            params,
            mcp_error(
                ErrorCode.NOT_FOUND,
                "directory not found",
                {"directory": str(directory)},
            ),
        )
    return log_tool("list_requirements", params, _page_to_payload(page_data))


def get_requirement(directory: str | Path, rid: str) -> dict:
    params = {"directory": str(directory), "rid": rid}
    try:
        req = doc_store.get_requirement(directory, rid)
    except ValueError as exc:
        return log_tool(
            "get_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except doc_store.RequirementNotFoundError as exc:
        return log_tool(
            "get_requirement",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "get_requirement",
            params,
            mcp_error(ErrorCode.INTERNAL, str(exc)),
        )
    result = requirement_to_dict(req)
    result["rid"] = req.rid
    return log_tool("get_requirement", params, result)


def search_requirements(
    directory: str | Path,
    *,
    query: str | None = None,
    labels: Sequence[str] | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    params = {
        "directory": str(directory),
        "query": query,
        "labels": list(labels) if labels else None,
        "status": status,
        "page": page,
        "per_page": per_page,
    }
    try:
        page_data = doc_store.search_requirements(
            directory,
            query=query,
            labels=labels,
            status=status,
            page=page,
            per_page=per_page,
        )
    except FileNotFoundError:
        return log_tool(
            "search_requirements",
            params,
            mcp_error(
                ErrorCode.NOT_FOUND,
                "directory not found",
                {"directory": str(directory)},
            ),
        )
    return log_tool("search_requirements", params, _page_to_payload(page_data))
