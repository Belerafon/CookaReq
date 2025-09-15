"""Additional business rules for requirements."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .schema import validate as validate_schema


class ValidationError(Exception):
    """Raised when business rules are violated."""


def validate(
    data: dict,
    directory: str | Path,
    existing_ids: Iterable[int] | None = None,
) -> None:
    """Validate *data* using schema and business rules.

    Parameters
    ----------
    data:
        Requirement data as dictionary.
    directory:
        Path to requirement storage used to resolve cross-references.
    existing_ids:
        Optional set of identifiers already present (excluding ``data['id']``).
    """
    from . import store  # local import to avoid circular dependency

    validate_schema(data)
    directory = Path(directory)

    all_ids = store.load_index(directory)
    if existing_ids is None:
        ids = set(all_ids)
        ids.discard(data["id"])
    else:
        ids = existing_ids if isinstance(existing_ids, set) else set(existing_ids)

    if data["id"] in ids:
        raise ValidationError(f"duplicate id: {data['id']}")

    links: list[dict] = []
    if parent := data.get("parent"):
        links.append(parent)
    links.extend(data.get("derived_from", []))
    links.extend(data.get("derived_to", []))
    links_data = data.get("links", {})
    links.extend(links_data.get("verifies", []))
    links.extend(links_data.get("relates", []))

    for link in links:
        rid = link.get("rid")
        if rid is None:
            continue
        if rid.isdigit():
            ref_id = int(rid)
        else:
            ref_id = None
        if ref_id is not None and ref_id == data["id"]:
            raise ValidationError("link references self")
        if ref_id is not None and ref_id not in all_ids:
            raise ValidationError(f"missing source id: {rid}")

    for link in data.get("derived_from", []):
        rid = link.get("rid")
        if not rid or not rid.isdigit():
            continue
        ref_id = int(rid)
        src_path = directory / store.filename_for(ref_id)
        src_data, _ = store.load(src_path)
        for back in src_data.get("derived_to", []) + src_data.get("derived_from", []):
            back_rid = back.get("rid")
            if back_rid and back_rid.isdigit() and int(back_rid) == data["id"]:
                raise ValidationError(f"cyclic derivation via {rid}")
