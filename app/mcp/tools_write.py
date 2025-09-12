"""Requirement mutation utilities for MCP server."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from app.core.schema import SCHEMA
from app.core.model import requirement_from_dict, requirement_to_dict
from app.core.store import (
    load,
    save,
    delete as delete_file,
    filename_for,
    ConflictError,
)

# Fields that must not be modified directly through patching
UNPATCHABLE_FIELDS = {"id", "revision", "derived_from"}

# Known requirement fields
KNOWN_FIELDS = set(SCHEMA["properties"].keys())


def _load_requirement(directory: str | Path, req_id: int) -> tuple[dict[str, Any], float]:
    path = Path(directory) / filename_for(req_id)
    return load(path)


def create_requirement(directory: str | Path, data: Mapping[str, Any]) -> dict:
    """Create a new requirement in ``directory`` from ``data``.

    The revision is initialised to ``1`` regardless of provided value. Returns
    the created requirement as a dictionary.
    """
    req = dict(data)
    req["revision"] = 1
    obj = requirement_from_dict(req)
    save(directory, obj)
    return requirement_to_dict(obj)


def patch_requirement(
    directory: str | Path,
    req_id: int,
    patches: Mapping[str, Any],
    *,
    rev: int,
) -> dict:
    """Apply ``patches`` to requirement ``req_id`` stored in ``directory``.

    ``rev`` must match the current revision. ``id`` and other service fields are
    immutable. Returns the updated requirement as a dictionary.
    """
    data, mtime = _load_requirement(directory, req_id)
    current = data.get("revision")
    if current != rev:
        raise ConflictError(f"revision mismatch: expected {rev}, have {current}")

    for field in patches:
        if field in UNPATCHABLE_FIELDS:
            raise ValueError(f"field is read-only: {field}")
        if field not in KNOWN_FIELDS:
            raise KeyError(field)

    data.update(patches)
    data["revision"] = current + 1
    obj = requirement_from_dict(data)
    save(directory, obj, mtime=mtime)
    return requirement_to_dict(obj)


def delete_requirement(directory: str | Path, req_id: int, *, rev: int) -> None:
    """Delete requirement ``req_id`` from ``directory`` if ``rev`` matches."""
    data, _ = _load_requirement(directory, req_id)
    current = data.get("revision")
    if current != rev:
        raise ConflictError(f"revision mismatch: expected {rev}, have {current}")
    delete_file(directory, req_id)


def link_requirements(
    directory: str | Path,
    *,
    source_id: int,
    derived_id: int,
    rev: int,
) -> dict:
    """Link ``derived_id`` requirement to ``source_id``.

    ``rev`` must match the current revision of the derived requirement. Stores
    the current revision of the source requirement. Returns the updated derived
    requirement as a dictionary.
    """
    src_data, _ = _load_requirement(directory, source_id)
    src_revision = src_data.get("revision", 1)

    data, mtime = _load_requirement(directory, derived_id)
    current = data.get("revision")
    if current != rev:
        raise ConflictError(f"revision mismatch: expected {rev}, have {current}")

    links = [l for l in data.get("derived_from", []) if l.get("source_id") != source_id]
    links.append({"source_id": source_id, "source_revision": src_revision, "suspect": False})
    data["derived_from"] = links
    data["revision"] = current + 1
    obj = requirement_from_dict(data)
    save(directory, obj, mtime=mtime)
    return requirement_to_dict(obj)
