"""Read-oriented MCP tool implementations."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..core.model import Requirement
from ..services.requirements import (
    DocumentNotFoundError,
    RequirementNotFoundError,
    RequirementPage,
)
from .server import get_requirements_service
from .utils import ErrorCode, log_tool, mcp_error

_SEQUENCE_STRING_TYPES = (str, bytes, bytearray)
_AVAILABLE_FIELDS = frozenset(
    field
    for field in Requirement.__dataclass_fields__
    if field not in {"doc_prefix", "rid"}
)


def _normalize_rid_argument(
    rid: str | Sequence[str],
) -> tuple[list[str], str | list[str]]:
    """Return a deduplicated list of RIDs and a log-friendly representation."""
    if isinstance(rid, _SEQUENCE_STRING_TYPES):
        rid_value = str(rid).strip()
        if not rid_value:
            raise ValueError("rid must be a non-empty string")
        return [rid_value], rid_value

    if not isinstance(rid, Sequence):
        raise ValueError("rid must be a string or a sequence of strings")

    normalized: list[str] = []
    logged: list[str] = []
    seen: set[str] = set()
    for entry in rid:
        if not isinstance(entry, _SEQUENCE_STRING_TYPES):
            raise ValueError("rid entries must be strings")
        rid_value = str(entry).strip()
        if not rid_value:
            raise ValueError("rid entries must be non-empty strings")
        logged.append(rid_value)
        if rid_value in seen:
            continue
        normalized.append(rid_value)
        seen.add(rid_value)

    if not normalized:
        raise ValueError("rid list must contain at least one identifier")

    return normalized, logged


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
    page: RequirementPage, fields: list[str] | None
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for req in page.items:
        data: dict[str, Any] = req.to_mapping()
        data["rid"] = req.rid
        items.append(_apply_field_selection(data, fields))
    hint = _build_list_pagination_hint(page, len(items))
    return {
        "total": page.total,
        "page": page.page,
        "per_page": page.per_page,
        "items": items,
        "usage_hint": hint,
    }


def _build_list_pagination_hint(page: RequirementPage, returned: int) -> str:
    total = page.total
    requested = page.per_page
    page_number = page.page

    if total == 0:
        return (
            "No requirements were found for the selected parameters. Adjust the filters "
            "or directory and try again."
        )

    base = (
        f"Requested {requested} requirements on page {page_number}; received {returned} "
        f"of {total}."
    )

    if returned == 0:
        return base + " This page has no items—check the page and per_page values."

    if page_number * requested < total:
        next_page = page_number + 1
        return (
            base
            + f" To fetch the rest, call list_requirements with page={next_page} and the same "
            f"per_page, or set per_page={total} to retrieve everything at once."
        )

    return base + " This is the last page; no additional records are available."


def list_requirements(
    directory: str | Path,
    *,
    prefix: str,
    page: int = 1,
    per_page: int = 50,
    status: str | None = None,
    labels: Sequence[str] | None = None,
    fields: Sequence[str] | None = None,
) -> dict:
    """Return a paginated requirements listing payload for MCP responses."""
    normalized_fields, logged_fields = _prepare_field_selection(fields)
    params = {
        "directory": str(directory),
        "prefix": prefix,
        "page": page,
        "per_page": per_page,
        "status": status,
        "labels": list(labels) if labels else None,
        "fields": logged_fields,
    }
    service = get_requirements_service(directory)
    try:
        document = service.get_document(prefix)
    except DocumentNotFoundError:
        return log_tool(
            "list_requirements",
            params,
            mcp_error(
                ErrorCode.NOT_FOUND,
                "requirements document not found",
                {"prefix": prefix},
            ),
        )
    try:
        page_data = service.list_requirements(
            prefix=prefix,
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
    payload = _page_to_payload(page_data, normalized_fields)
    payload["document"] = {"prefix": document.prefix, "title": document.title}
    return log_tool("list_requirements", params, payload)


def get_requirement(
    directory: str | Path,
    rid: str | Sequence[str],
    fields: Sequence[str] | None = None,
) -> dict:
    """Return requirement details for one or more requirement identifiers."""
    normalized_fields, logged_fields = _prepare_field_selection(fields)
    params: dict[str, Any] = {
        "directory": str(directory),
        "fields": logged_fields,
    }
    service = get_requirements_service(directory)
    try:
        requested_rids, logged_rid = _normalize_rid_argument(rid)
    except ValueError as exc:
        params["rid"] = rid
        return log_tool(
            "get_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )

    params["rid"] = logged_rid

    if isinstance(rid, _SEQUENCE_STRING_TYPES):
        rid_value = requested_rids[0]
        try:
            req = service.get_requirement(rid_value)
        except ValueError as exc:
            return log_tool(
                "get_requirement",
                params,
                mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
            )
        except RequirementNotFoundError as exc:
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
        result: dict[str, Any] = req.to_mapping()
        result["rid"] = req.rid
        return log_tool(
            "get_requirement",
            params,
            _apply_field_selection(result, normalized_fields),
        )

    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for rid_value in requested_rids:
        try:
            req = service.get_requirement(rid_value)
        except ValueError as exc:
            return log_tool(
                "get_requirement",
                params,
                mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
            )
        except RequirementNotFoundError:
            missing.append(rid_value)
            continue
        except Exception as exc:  # pragma: no cover - defensive
            return log_tool(
                "get_requirement",
                params,
                mcp_error(ErrorCode.INTERNAL, str(exc)),
            )
        data = req.to_mapping()
        data["rid"] = req.rid
        items.append(_apply_field_selection(data, normalized_fields))

    payload: dict[str, Any] = {"items": items}
    if missing:
        payload["missing"] = missing
    return log_tool("get_requirement", params, payload)


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
    """Return search results from the MCP requirements store."""
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
    service = get_requirements_service(directory)
    try:
        page_data = service.search_requirements(
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


def list_labels(directory: str | Path, *, prefix: str) -> dict:
    """Return label definitions accessible to document ``prefix``."""
    params = {"directory": str(directory), "prefix": prefix}
    service = get_requirements_service(directory)
    try:
        payload = service.describe_label_definitions(prefix)
    except DocumentNotFoundError as exc:
        return log_tool("list_labels", params, mcp_error(ErrorCode.NOT_FOUND, str(exc)))
    except Exception as exc:  # pragma: no cover - defensive guard
        return log_tool("list_labels", params, mcp_error(ErrorCode.INTERNAL, str(exc)))
    return log_tool("list_labels", params, payload)
