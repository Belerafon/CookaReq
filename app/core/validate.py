from __future__ import annotations
"""Additional business rules for requirements."""

from typing import Iterable

from .schema import validate as validate_schema


class ValidationError(Exception):
    """Raised when business rules are violated."""


def validate(data: dict, existing_ids: Iterable[int] = ()) -> None:
    """Validate *data* using schema and business rules.

    Parameters
    ----------
    data:
        Requirement data as dictionary.
    existing_ids:
        Iterable of identifiers already present in the store.
    """
    validate_schema(data)
    ids = existing_ids if isinstance(existing_ids, set) else set(existing_ids)
    if data["id"] in ids:
        raise ValidationError(f"duplicate id: {data['id']}")
