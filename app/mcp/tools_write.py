from __future__ import annotations

from dataclasses import fields
from pathlib import Path
from typing import Any, Mapping

import jsonpatch

from ..core.doc_store import (
    collect_labels,
    delete_item,
    is_ancestor,
    load_documents,
    load_item,
    next_item_id,
    parse_rid,
    rid_for,
    save_item,
)
from ..core.model import Requirement, requirement_from_dict, requirement_to_dict
from .utils import ErrorCode, log_tool, mcp_error

# Fields that cannot be modified via JSON Patch
UNPATCHABLE_FIELDS = {"id", "revision", "links"}

# Known top-level fields for validation
KNOWN_FIELDS = {f.name for f in fields(Requirement)}


def create_requirement(directory: str | Path, *, prefix: str, data: Mapping[str, Any]) -> dict:
    """Create a new requirement under *prefix* document."""
    params = {"directory": str(directory), "prefix": prefix, "data": dict(data)}
    try:
        docs = load_documents(directory)
        doc = docs.get(prefix)
        if doc is None:
            return log_tool(
                "create_requirement",
                params,
                mcp_error(ErrorCode.NOT_FOUND, f"unknown document prefix: {prefix}"),
            )
        allowed, freeform = collect_labels(prefix, docs)
        labels = list(data.get("labels", []))
        if labels and not freeform:
            unknown = [lbl for lbl in labels if lbl not in allowed]
            if unknown:
                return log_tool(
                    "create_requirement",
                    params,
                    mcp_error(ErrorCode.VALIDATION_ERROR, f"unknown label: {unknown[0]}"),
                )
        doc_dir = Path(directory) / prefix
        item_id = next_item_id(doc_dir, doc)
        req_dict = dict(data)
        req_dict["id"] = item_id
        req_dict["revision"] = 1
        req = requirement_from_dict(req_dict, doc_prefix=prefix, rid=rid_for(doc, item_id))
        save_item(doc_dir, doc, requirement_to_dict(req))
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "create_requirement", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    result = requirement_to_dict(req)
    result["rid"] = req.rid
    return log_tool("create_requirement", params, result)


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
        prefix, item_id = parse_rid(rid)
    except ValueError as exc:
        return log_tool(
            "patch_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    try:
        docs = load_documents(directory)
        doc = docs.get(prefix)
        if doc is None:
            raise FileNotFoundError
        dir_path = Path(directory) / prefix
        data, _mtime = load_item(dir_path, doc, item_id)
    except FileNotFoundError:
        return log_tool(
            "patch_requirement",
            params,
            mcp_error(ErrorCode.NOT_FOUND, f"requirement {rid} not found"),
        )

    current = data.get("revision", 1)
    if current != rev:
        return log_tool(
            "patch_requirement",
            params,
            mcp_error(
                ErrorCode.CONFLICT,
                f"revision mismatch: expected {rev}, have {current}",
            ),
        )

    for op in patch:
        for key in ("path", "from"):
            p = op.get(key)
            if not p:
                continue
            target = p.lstrip("/").split("/", 1)[0]
            if target in UNPATCHABLE_FIELDS:
                return log_tool(
                    "patch_requirement",
                    params,
                    mcp_error(ErrorCode.VALIDATION_ERROR, f"field is read-only: {target}"),
                )
            if target and target not in KNOWN_FIELDS:
                return log_tool(
                    "patch_requirement",
                    params,
                    mcp_error(ErrorCode.VALIDATION_ERROR, f"unknown field: {target}"),
                )
    try:
        data = jsonpatch.apply_patch(data, patch, in_place=False)
    except jsonpatch.JsonPatchException as exc:
        return log_tool(
            "patch_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )

    data["revision"] = current + 1
    allowed, freeform = collect_labels(prefix, docs)
    labels = data.get("labels", [])
    if labels and not freeform:
        unknown = [lbl for lbl in labels if lbl not in allowed]
        if unknown:
            return log_tool(
                "patch_requirement",
                params,
                mcp_error(ErrorCode.VALIDATION_ERROR, f"unknown label: {unknown[0]}"),
            )
    try:
        req = requirement_from_dict(data, doc_prefix=prefix, rid=rid)
        save_item(dir_path, doc, requirement_to_dict(req))
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "patch_requirement", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    result = requirement_to_dict(req)
    result["rid"] = rid
    return log_tool("patch_requirement", params, result)


def delete_requirement(directory: str | Path, rid: str, *, rev: int) -> dict:
    """Delete requirement *rid* if revision matches."""
    params = {"directory": str(directory), "rid": rid, "rev": rev}
    try:
        prefix, _ = parse_rid(rid)
    except ValueError as exc:
        return log_tool(
            "delete_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )
    docs = load_documents(directory)
    doc = docs.get(prefix)
    if doc is None:
        return log_tool(
            "delete_requirement",
            params,
            mcp_error(ErrorCode.NOT_FOUND, f"requirement {rid} not found"),
        )
    try:
        data, _ = load_item(Path(directory) / prefix, doc, parse_rid(rid)[1])
    except FileNotFoundError:
        return log_tool(
            "delete_requirement",
            params,
            mcp_error(ErrorCode.NOT_FOUND, f"requirement {rid} not found"),
        )
    current = data.get("revision", 1)
    if current != rev:
        return log_tool(
            "delete_requirement",
            params,
            mcp_error(
                ErrorCode.CONFLICT,
                f"revision mismatch: expected {rev}, have {current}",
            ),
        )
    try:
        delete_item(directory, rid, docs)
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
    result = requirement_to_dict(req)
    result["rid"] = derived_rid
    return log_tool("link_requirements", params, result)
