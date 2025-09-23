from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from ..core import document_store as doc_store
from ..core.model import requirement_to_dict
from .utils import ErrorCode, log_tool, mcp_error


def _result_payload(req) -> dict:
    data = requirement_to_dict(req)
    data["rid"] = req.rid
    return data


def create_requirement(directory: str | Path, *, prefix: str, data: Mapping[str, Any]) -> dict:
    """Create a new requirement under *prefix* document."""
    params = {"directory": str(directory), "prefix": prefix, "data": dict(data)}
    try:
        req = doc_store.create_requirement(directory, prefix=prefix, data=data)
    except doc_store.DocumentNotFoundError as exc:
        return log_tool(
            "create_requirement",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except doc_store.ValidationError as exc:
        return log_tool(
            "create_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "create_requirement", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    return log_tool("create_requirement", params, _result_payload(req))


def update_requirement_field(
    directory: str | Path,
    rid: str,
    *,
    field: str,
    value: Any,
) -> dict:
    """Update a single field of a requirement."""

    params = {
        "directory": str(directory),
        "rid": rid,
        "field": field,
        "value": value,
    }
    try:
        req = doc_store.update_requirement_field(
            directory,
            rid,
            field=field,
            value=value,
        )
    except doc_store.RequirementNotFoundError as exc:
        return log_tool(
            "update_requirement_field",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except doc_store.ValidationError as exc:
        return log_tool(
            "update_requirement_field",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "update_requirement_field",
            params,
            mcp_error(ErrorCode.INTERNAL, str(exc)),
        )
    return log_tool("update_requirement_field", params, _result_payload(req))


def set_requirement_labels(
    directory: str | Path,
    rid: str,
    labels: Sequence[str] | None,
) -> dict:
    """Replace the label list of a requirement."""

    params = {
        "directory": str(directory),
        "rid": rid,
        "labels": labels,
    }
    try:
        req = doc_store.set_requirement_labels(
            directory,
            rid,
            labels=labels,
        )
    except doc_store.RequirementNotFoundError as exc:
        return log_tool(
            "set_requirement_labels",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except doc_store.ValidationError as exc:
        return log_tool(
            "set_requirement_labels",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "set_requirement_labels",
            params,
            mcp_error(ErrorCode.INTERNAL, str(exc)),
        )
    return log_tool("set_requirement_labels", params, _result_payload(req))


def set_requirement_attachments(
    directory: str | Path,
    rid: str,
    attachments: Sequence[Mapping[str, Any]] | None,
) -> dict:
    """Replace attachments of a requirement."""

    params = {
        "directory": str(directory),
        "rid": rid,
        "attachments": attachments,
    }
    try:
        req = doc_store.set_requirement_attachments(
            directory,
            rid,
            attachments=attachments,
        )
    except doc_store.RequirementNotFoundError as exc:
        return log_tool(
            "set_requirement_attachments",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except (doc_store.ValidationError, TypeError, ValueError) as exc:
        return log_tool(
            "set_requirement_attachments",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "set_requirement_attachments",
            params,
            mcp_error(ErrorCode.INTERNAL, str(exc)),
        )
    return log_tool("set_requirement_attachments", params, _result_payload(req))


def set_requirement_links(
    directory: str | Path,
    rid: str,
    links: Sequence[Mapping[str, Any]] | Sequence[str] | None,
) -> dict:
    """Replace the outgoing links of a requirement."""

    params = {
        "directory": str(directory),
        "rid": rid,
        "links": links,
    }
    try:
        req = doc_store.set_requirement_links(
            directory,
            rid,
            links=links,
        )
    except doc_store.RequirementNotFoundError as exc:
        return log_tool(
            "set_requirement_links",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except (doc_store.ValidationError, TypeError, ValueError) as exc:
        return log_tool(
            "set_requirement_links",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "set_requirement_links",
            params,
            mcp_error(ErrorCode.INTERNAL, str(exc)),
        )
    return log_tool("set_requirement_links", params, _result_payload(req))


def delete_requirement(directory: str | Path, rid: str) -> dict:
    """Delete requirement *rid* from the document store."""
    params = {"directory": str(directory), "rid": rid}
    try:
        doc_store.delete_requirement(directory, rid)
    except ValueError as exc:
        return log_tool(
            "delete_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except doc_store.ValidationError as exc:
        return log_tool(
            "delete_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except doc_store.RequirementNotFoundError as exc:
        return log_tool(
            "delete_requirement",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "delete_requirement", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    return log_tool("delete_requirement", params, {"rid": rid})


def link_requirements(
    directory: str | Path,
    *,
    source_rid: str,
    derived_rid: str,
    link_type: str,
) -> dict:
    """Link *derived_rid* to *source_rid* when hierarchy permits."""
    params = {
        "directory": str(directory),
        "source_rid": source_rid,
        "derived_rid": derived_rid,
        "link_type": link_type,
    }
    try:
        req = doc_store.link_requirements(
            directory,
            source_rid=source_rid,
            derived_rid=derived_rid,
            link_type=link_type,
        )
    except doc_store.ValidationError as exc:
        return log_tool(
            "link_requirements",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except doc_store.RequirementNotFoundError as exc:
        return log_tool(
            "link_requirements",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "link_requirements", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    return log_tool("link_requirements", params, _result_payload(req))
