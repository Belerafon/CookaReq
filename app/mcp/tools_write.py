from __future__ import annotations

from pathlib import Path
from typing import Any
from collections.abc import Mapping, Sequence

from ..core.model import requirement_to_dict
from ..services.requirements import (
    RequirementsService,
    DocumentNotFoundError,
    RequirementNotFoundError,
    ValidationError,
)
from .utils import ErrorCode, log_tool, mcp_error


def _result_payload(req) -> dict:
    data = requirement_to_dict(req)
    data["rid"] = req.rid
    return data


def create_requirement(directory: str | Path, *, prefix: str, data: Mapping[str, Any]) -> dict:
    """Create a new requirement under *prefix* document."""
    params = {"directory": str(directory), "prefix": prefix, "data": dict(data)}
    service = RequirementsService(directory)
    try:
        req = service.create_requirement(prefix=prefix, data=data)
    except DocumentNotFoundError as exc:
        return log_tool(
            "create_requirement",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except ValidationError as exc:
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
    service = RequirementsService(directory)
    before_snapshot: dict[str, Any] | None = None
    try:
        previous = service.get_requirement(rid)
    except RequirementNotFoundError as exc:
        return log_tool(
            "update_requirement_field",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except DocumentNotFoundError as exc:
        return log_tool(
            "update_requirement_field",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    else:
        before_snapshot = requirement_to_dict(previous)
    try:
        req = service.update_requirement_field(rid, field=field, value=value)
    except RequirementNotFoundError as exc:
        return log_tool(
            "update_requirement_field",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except ValidationError as exc:
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

    payload = _result_payload(req)
    if before_snapshot is not None:
        after_snapshot = dict(payload)
        previous_value = before_snapshot.get(field)
        current_value = after_snapshot.get(field)
        payload["field_change"] = {
            "field": field,
            "previous": previous_value,
            "current": current_value,
        }
    return log_tool("update_requirement_field", params, payload)


def set_requirement_labels(
    directory: str | Path,
    rid: str,
    labels: Sequence[str],
) -> dict:
    """Replace the label list of a requirement."""

    params = {
        "directory": str(directory),
        "rid": rid,
        "labels": labels,
    }
    if isinstance(labels, (str, bytes)):
        return log_tool(
            "set_requirement_labels",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, "labels must be an array of strings"),
        )
    service = RequirementsService(directory)
    try:
        req = service.set_requirement_labels(rid, labels=labels)
    except RequirementNotFoundError as exc:
        return log_tool(
            "set_requirement_labels",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except ValidationError as exc:
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
    attachments: Sequence[Mapping[str, Any]],
) -> dict:
    """Replace attachments of a requirement."""

    params = {
        "directory": str(directory),
        "rid": rid,
        "attachments": attachments,
    }
    if isinstance(attachments, (str, bytes)):
        return log_tool(
            "set_requirement_attachments",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, "attachments must be an array"),
        )
    service = RequirementsService(directory)
    try:
        req = service.set_requirement_attachments(rid, attachments=attachments)
    except RequirementNotFoundError as exc:
        return log_tool(
            "set_requirement_attachments",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except (ValidationError, TypeError, ValueError) as exc:
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
    links: Sequence[Mapping[str, Any] | str],
) -> dict:
    """Replace the outgoing links of a requirement."""

    params = {
        "directory": str(directory),
        "rid": rid,
        "links": links,
    }
    if isinstance(links, (str, bytes)):
        return log_tool(
            "set_requirement_links",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, "links must be an array"),
        )
    service = RequirementsService(directory)
    try:
        req = service.set_requirement_links(rid, links=links)
    except RequirementNotFoundError as exc:
        return log_tool(
            "set_requirement_links",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except (ValidationError, TypeError, ValueError) as exc:
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
    service = RequirementsService(directory)
    try:
        canonical = service.delete_requirement(rid)
    except ValueError as exc:
        return log_tool(
            "delete_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except ValidationError as exc:
        return log_tool(
            "delete_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except RequirementNotFoundError as exc:
        return log_tool(
            "delete_requirement",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "delete_requirement", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    return log_tool("delete_requirement", params, {"rid": canonical})


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
    service = RequirementsService(directory)
    try:
        req = service.link_requirements(
            source_rid=source_rid,
            derived_rid=derived_rid,
            link_type=link_type,
        )
    except ValidationError as exc:
        return log_tool(
            "link_requirements",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except RequirementNotFoundError as exc:
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
