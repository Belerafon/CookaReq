from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..core import document_store as doc_store
from ..core.model import Requirement, requirement_to_dict
from .utils import ErrorCode, log_tool, mcp_error

_SEQUENCE_STRING_TYPES = (str, bytes, bytearray)
_AVAILABLE_FIELDS = frozenset(
    field
    for field in Requirement.__dataclass_fields__
    if field not in {"doc_prefix", "rid"}
)


def _prepare_field_selection(
    fields: Sequence[str] | None,
) -> tuple[list[str] | None, list[str] | None]:
    """Return normalized field names and a JSON-serialisable log copy."""

    if fields is None:
        return None, None
    if not isinstance(fields, Sequence) or isinstance(fields, _SEQUENCE_STRING_TYPES):
        return None, None

    try:
        logged = [str(item) for item in fields]
    except Exception:  # pragma: no cover - defensive
        logged = None

    normalized: list[str] = []
    seen: set[str] = set()
    for entry in fields:
        if not isinstance(entry, str):
            return None, logged
        name = entry.strip()
        if not name or name == "rid":
            continue
        if name in _AVAILABLE_FIELDS and name not in seen:
            normalized.append(name)
            seen.add(name)
    return normalized, logged


def _apply_field_selection(data: Mapping[str, Any], fields: list[str] | None) -> dict:
    """Return ``data`` filtered by ``fields`` while preserving the RID."""

    rid = data.get("rid")
    if rid is None:
        raise KeyError("requirement payload missing rid")

    if not fields:
        return dict(data)

    filtered: dict[str, Any] = {"rid": rid}
    for field in fields:
        if field in data:
            filtered[field] = data[field]
    return filtered


def _page_to_payload(
    page: doc_store.RequirementPage, fields: list[str] | None
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for req in page.items:
        data: dict[str, Any] = requirement_to_dict(req)
        data["rid"] = req.rid
        items.append(_apply_field_selection(data, fields))
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
    fields: Sequence[str] | None = None,
) -> dict:
    normalized_fields, logged_fields = _prepare_field_selection(fields)
    params = {
        "directory": str(directory),
        "page": page,
        "per_page": per_page,
        "status": status,
        "labels": list(labels) if labels else None,
        "fields": logged_fields,
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
    return log_tool(
        "list_requirements",
        params,
        _page_to_payload(page_data, normalized_fields),
    )


def get_requirement(
    directory: str | Path, rid: str, fields: Sequence[str] | None = None
) -> dict:
    normalized_fields, logged_fields = _prepare_field_selection(fields)
    params: dict[str, Any] = {
        "directory": str(directory),
        "rid": rid,
        "fields": logged_fields,
    }
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
    result: dict[str, Any] = requirement_to_dict(req)
    result["rid"] = req.rid
    return log_tool(
        "get_requirement",
        params,
        _apply_field_selection(result, normalized_fields),
    )


def search_requirements(
    directory: str | Path,
    *,
    query: str | None = None,
    labels: Sequence[str] | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 50,
    fields: Sequence[str] | None = None,
) -> dict:
    normalized_fields, logged_fields = _prepare_field_selection(fields)
    params = {
        "directory": str(directory),
        "query": query,
        "labels": list(labels) if labels else None,
        "status": status,
        "page": page,
        "per_page": per_page,
        "fields": logged_fields,
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
    return log_tool(
        "search_requirements",
        params,
        _page_to_payload(page_data, normalized_fields),
    )
