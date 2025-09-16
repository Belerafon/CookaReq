from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

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


def patch_requirement(
    directory: str | Path,
    rid: str,
    patch: list[dict[str, Any]],
    *,
    rev: int,
) -> dict:
    """Apply JSON Patch *patch* to requirement *rid* if revision matches."""
    params = {"directory": str(directory), "rid": rid, "patch": patch, "rev": rev}
    try:
        req = doc_store.patch_requirement(
            directory,
            rid,
            patch,
            expected_revision=rev,
        )
    except ValueError as exc:
        return log_tool(
            "patch_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except doc_store.RevisionMismatchError as exc:
        return log_tool(
            "patch_requirement",
            params,
            mcp_error(ErrorCode.CONFLICT, str(exc)),
        )
    except doc_store.RequirementNotFoundError as exc:
        return log_tool(
            "patch_requirement",
            params,
            mcp_error(ErrorCode.NOT_FOUND, str(exc)),
        )
    except doc_store.ValidationError as exc:
        return log_tool(
            "patch_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "patch_requirement", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    return log_tool("patch_requirement", params, _result_payload(req))


def delete_requirement(directory: str | Path, rid: str, *, rev: int) -> dict:
    """Delete requirement *rid* if revision matches."""
    params = {"directory": str(directory), "rid": rid, "rev": rev}
    try:
        doc_store.delete_requirement(directory, rid, expected_revision=rev)
    except ValueError as exc:
        return log_tool(
            "delete_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except doc_store.RevisionMismatchError as exc:
        return log_tool(
            "delete_requirement",
            params,
            mcp_error(ErrorCode.CONFLICT, str(exc)),
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
    rev: int,
) -> dict:
    """Link *derived_rid* to *source_rid* when hierarchy permits."""
    params = {
        "directory": str(directory),
        "source_rid": source_rid,
        "derived_rid": derived_rid,
        "link_type": link_type,
        "rev": rev,
    }
    try:
        req = doc_store.link_requirements(
            directory,
            source_rid=source_rid,
            derived_rid=derived_rid,
            link_type=link_type,
            expected_revision=rev,
        )
    except doc_store.ValidationError as exc:
        return log_tool(
            "link_requirements",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    except doc_store.RevisionMismatchError as exc:
        return log_tool(
            "link_requirements",
            params,
            mcp_error(ErrorCode.CONFLICT, str(exc)),
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
