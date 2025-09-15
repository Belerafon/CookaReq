from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..core.doc_store import (
    load_documents,
    list_item_ids,
    load_document,
    load_item,
    parse_rid,
    rid_for,
)
from ..core.model import Requirement, requirement_from_dict, requirement_to_dict
from ..core.search import filter_by_labels, filter_by_status, search
from .utils import ErrorCode, log_tool, mcp_error


def _load_all(directory: str | Path) -> list[Requirement]:
    root = Path(directory)
    docs = load_documents(root)
    items: list[Requirement] = []
    for prefix, doc in docs.items():
        dir_path = root / prefix
        for item_id in list_item_ids(dir_path, doc):
            data, _ = load_item(dir_path, doc, item_id)
            req = requirement_from_dict(data, doc_prefix=prefix, rid=rid_for(doc, item_id))
            items.append(req)
    return items


def _paginate(requirements: Sequence[Requirement], page: int, per_page: int) -> dict:
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 1
    total = len(requirements)
    start = (page - 1) * per_page
    end = start + per_page
    items = []
    for r in requirements[start:end]:
        data = requirement_to_dict(r)
        data["rid"] = r.rid
        items.append(data)
    return {"total": total, "page": page, "per_page": per_page, "items": items}


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
        reqs = _load_all(directory)
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
    reqs = filter_by_status(reqs, status)
    reqs = filter_by_labels(reqs, labels or [])
    return log_tool("list_requirements", params, _paginate(reqs, page, per_page))


def get_requirement(directory: str | Path, rid: str) -> dict:
    params = {"directory": str(directory), "rid": rid}
    try:
        prefix, item_id = parse_rid(rid)
        doc = load_document(Path(directory) / prefix)
        data, _ = load_item(Path(directory) / prefix, doc, item_id)
        req = requirement_from_dict(data, doc_prefix=prefix, rid=rid)
    except FileNotFoundError:
        return log_tool(
            "get_requirement",
            params,
            mcp_error(ErrorCode.NOT_FOUND, f"requirement {rid} not found"),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "get_requirement",
            params,
            mcp_error(ErrorCode.INTERNAL, str(exc)),
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
    params = {
        "directory": str(directory),
        "query": query,
        "labels": list(labels) if labels else None,
        "status": status,
        "page": page,
        "per_page": per_page,
    }
    try:
        reqs = _load_all(directory)
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
    reqs = filter_by_status(reqs, status)
    reqs = search(reqs, labels=labels, query=query)
    return log_tool("search_requirements", params, _paginate(reqs, page, per_page))
