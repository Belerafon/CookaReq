from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..core import doc_store
from ..core.doc_store import is_ancestor, load_documents, load_item, parse_rid, save_item
from ..core.model import requirement_from_dict, requirement_to_dict
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
    if link_type != "parent":
        return log_tool(
            "link_requirements",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, f"invalid link_type: {link_type}"),
        )
    try:
        src_prefix, src_id = parse_rid(source_rid)
        dst_prefix, dst_id = parse_rid(derived_rid)
    except ValueError as exc:
        return log_tool(
            "link_requirements",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    docs = load_documents(directory)
    src_doc = docs.get(src_prefix)
    dst_doc = docs.get(dst_prefix)
    if src_doc is None or dst_doc is None:
        return log_tool(
            "link_requirements",
            params,
            mcp_error(ErrorCode.NOT_FOUND, "document not found"),
        )
    if not is_ancestor(dst_prefix, src_prefix, docs):
        return log_tool(
            "link_requirements",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, f"invalid link target: {source_rid}"),
        )
    src_dir = Path(directory) / src_prefix
    dst_dir = Path(directory) / dst_prefix
    try:
        load_item(src_dir, src_doc, src_id)
        data, _ = load_item(dst_dir, dst_doc, dst_id)
    except FileNotFoundError:
        return log_tool(
            "link_requirements",
            params,
            mcp_error(ErrorCode.NOT_FOUND, "requirement not found"),
        )
    current = data.get("revision", 1)
    if current != rev:
        return log_tool(
            "link_requirements",
            params,
            mcp_error(
                ErrorCode.CONFLICT,
                f"revision mismatch: expected {rev}, have {current}",
            ),
        )
    links = sorted(set(data.get("links", [])) | {source_rid})
    data["links"] = links
    data["revision"] = current + 1
    try:
        req = requirement_from_dict(data, doc_prefix=dst_prefix, rid=derived_rid)
        save_item(dst_dir, dst_doc, requirement_to_dict(req))
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "link_requirements", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    return log_tool("link_requirements", params, _result_payload(req))
