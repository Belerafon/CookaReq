from __future__ import annotations
"""Additional business rules for requirements."""

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

    for link in data.get("derived_from", []):
        src_id = link.get("source_id")
        if src_id == data["id"]:
            raise ValidationError("derived_from references self")
        if src_id not in all_ids:
            raise ValidationError(f"missing source id: {src_id}")

        src_path = directory / store.filename_for(src_id)
        src_data, _ = store.load(src_path)
        for back in src_data.get("derived_from", []):
            if back.get("source_id") == data["id"]:
                raise ValidationError(f"cyclic derivation via {src_id}")
