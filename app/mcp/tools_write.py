"""Requirement mutation utilities for MCP server."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import jsonpatch
import jsonschema
from ..core.schema import SCHEMA
from ..core.model import requirement_from_dict, requirement_to_dict
from ..core.store import ConflictError
from ..core import requirements as req_ops
from .utils import ErrorCode, log_tool, mcp_error

# Fields that must not be modified directly through patching
UNPATCHABLE_FIELDS = {"id", "revision", "derived_from", "parent", "links"}

# Known requirement fields
KNOWN_FIELDS = set(SCHEMA["properties"].keys())


PATCH_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["op", "path"],
        "properties": {
            "op": {
                "type": "string",
                "enum": [
                    "add",
                    "remove",
                    "replace",
                    "move",
                    "copy",
                    "test",
                ],
            },
            "path": {"type": "string", "pattern": "^/"},
            "value": {},
            "from": {"type": "string", "pattern": "^/"},
        },
        "oneOf": [
            {
                "properties": {"op": {"enum": ["add", "replace", "test"]}},
                "required": ["value"],
            },
            {"properties": {"op": {"enum": ["remove"]}}},
            {
                "properties": {"op": {"enum": ["move", "copy"]}},
                "required": ["from"],
            },
        ],
        "additionalProperties": False,
    },
}

def create_requirement(directory: str | Path, data: Mapping[str, Any]) -> dict:
    """Create a new requirement in ``directory`` from ``data``.

    The revision is initialised to ``1`` regardless of provided value. Returns
    the created requirement as a dictionary.
    """
    params = {"directory": str(directory), "data": data}
    req = dict(data)
    req["revision"] = 1
    try:
        obj = requirement_from_dict(req)
        req_ops.save_requirement(directory, obj, modified_at=obj.modified_at or None)
    except ConflictError as exc:
        return log_tool(
            "create_requirement", params, mcp_error(ErrorCode.CONFLICT, str(exc))
        )
    except (ValueError, KeyError) as exc:
        return log_tool(
            "create_requirement", params, mcp_error(ErrorCode.VALIDATION_ERROR, str(exc))
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "create_requirement", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    return log_tool("create_requirement", params, requirement_to_dict(obj))


def patch_requirement(
    directory: str | Path,
    req_id: int,
    patch: list[dict[str, Any]],
    *,
    rev: int,
) -> dict:
    """Apply JSON Patch ``patch`` to requirement ``req_id`` stored in
    ``directory``.

    ``rev`` must match the current revision. ``id`` and other service fields are
    immutable. Returns the updated requirement as a dictionary.
    """
    params = {
        "directory": str(directory),
        "req_id": req_id,
        "patch": patch,
        "rev": rev,
    }
    try:
        data, mtime = req_ops.load_requirement(directory, req_id)
    except FileNotFoundError:
        return log_tool(
            "patch_requirement",
            params,
            mcp_error(ErrorCode.NOT_FOUND, f"requirement {req_id} not found"),
        )
    current = data.get("revision")
    if current != rev:
        return log_tool(
            "patch_requirement",
            params,
            mcp_error(
                ErrorCode.CONFLICT,
                f"revision mismatch: expected {rev}, have {current}",
            ),
        )

    try:
        jsonschema.validate(patch, PATCH_SCHEMA)
    except jsonschema.ValidationError as exc:
        return log_tool(
            "patch_requirement",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, str(exc)),
        )

    for op in patch:
        for key in ("path", "from"):
            if key not in op:
                continue
            target = op[key].lstrip("/").split("/", 1)[0]
            if target in UNPATCHABLE_FIELDS:
                return log_tool(
                    "patch_requirement",
                    params,
                    mcp_error(
                        ErrorCode.VALIDATION_ERROR,
                        f"field is read-only: {target}",
                    ),
                )
            if target and target not in KNOWN_FIELDS:
                return log_tool(
                    "patch_requirement",
                    params,
                    mcp_error(
                        ErrorCode.VALIDATION_ERROR,
                        f"unknown field: {target}",
                    ),
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
    try:
        obj = requirement_from_dict(data)
        mod = None
        for op in patch:
            if op.get("path") == "/modified_at" and op.get("op") in {"add", "replace"}:
                mod = data.get("modified_at")
                break
        req_ops.save_requirement(directory, obj, mtime=mtime, modified_at=mod)
    except ConflictError as exc:
        return log_tool(
            "patch_requirement", params, mcp_error(ErrorCode.CONFLICT, str(exc))
        )
    except (ValueError, KeyError) as exc:
        return log_tool(
            "patch_requirement", params, mcp_error(ErrorCode.VALIDATION_ERROR, str(exc))
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "patch_requirement", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    return log_tool("patch_requirement", params, requirement_to_dict(obj))


def delete_requirement(directory: str | Path, req_id: int, *, rev: int) -> dict | None:
    """Delete requirement ``req_id`` from ``directory`` if ``rev`` matches."""
    params = {"directory": str(directory), "req_id": req_id, "rev": rev}
    try:
        data, _ = req_ops.load_requirement(directory, req_id)
    except FileNotFoundError:
        return log_tool(
            "delete_requirement",
            params,
            mcp_error(ErrorCode.NOT_FOUND, f"requirement {req_id} not found"),
        )
    current = data.get("revision")
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
        req_ops.delete_requirement(directory, req_id)
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "delete_requirement", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    return log_tool("delete_requirement", params, {"id": req_id})


def link_requirements(
    directory: str | Path,
    *,
    source_id: int,
    derived_id: int,
    link_type: str,
    rev: int,
) -> dict:
    """Link ``derived_id`` requirement to ``source_id``.

    ``rev`` must match the current revision of the derived requirement. Stores
    the current revision of the source requirement. Returns the updated derived
    requirement as a dictionary.
    """
    params = {
        "directory": str(directory),
        "source_id": source_id,
        "derived_id": derived_id,
        "link_type": link_type,
        "rev": rev,
    }
    try:
        src_data, _ = req_ops.load_requirement(directory, source_id)
    except FileNotFoundError:
        return log_tool(
            "link_requirements",
            params,
            mcp_error(ErrorCode.NOT_FOUND, f"requirement {source_id} not found"),
        )
    src_revision = src_data.get("revision", 1)

    try:
        data, mtime = req_ops.load_requirement(directory, derived_id)
    except FileNotFoundError:
        return log_tool(
            "link_requirements",
            params,
            mcp_error(ErrorCode.NOT_FOUND, f"requirement {derived_id} not found"),
        )
    current = data.get("revision")
    if current != rev:
        return log_tool(
            "link_requirements",
            params,
            mcp_error(
                ErrorCode.CONFLICT,
                f"revision mismatch: expected {rev}, have {current}",
            ),
        )

    if link_type not in {"parent", "derived_from", "verifies", "relates"}:
        return log_tool(
            "link_requirements",
            params,
            mcp_error(ErrorCode.VALIDATION_ERROR, f"invalid link_type: {link_type}"),
        )

    link = {"source_id": source_id, "source_revision": src_revision, "suspect": False}
    if link_type == "parent":
        data["parent"] = link
    elif link_type == "derived_from":
        links = [l for l in data.get("derived_from", []) if l.get("source_id") != source_id]
        links.append(link)
        data["derived_from"] = links
    else:
        links_obj = data.get("links", {})
        lst = [l for l in links_obj.get(link_type, []) if l.get("source_id") != source_id]
        lst.append(link)
        links_obj[link_type] = lst
        data["links"] = links_obj
    data["revision"] = current + 1
    try:
        obj = requirement_from_dict(data)
        req_ops.save_requirement(directory, obj, mtime=mtime)
    except ConflictError as exc:
        return log_tool(
            "link_requirements", params, mcp_error(ErrorCode.CONFLICT, str(exc))
        )
    except (ValueError, KeyError) as exc:
        return log_tool(
            "link_requirements", params, mcp_error(ErrorCode.VALIDATION_ERROR, str(exc))
        )
    except Exception as exc:  # pragma: no cover - defensive
        return log_tool(
            "link_requirements", params, mcp_error(ErrorCode.INTERNAL, str(exc))
        )
    return log_tool("link_requirements", params, requirement_to_dict(obj))
