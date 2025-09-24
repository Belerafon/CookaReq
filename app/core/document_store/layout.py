"""Helpers for working with canonical requirement item filenames."""

from __future__ import annotations

__all__ = ["canonical_item_name"]


def canonical_item_name(item_id: int) -> str:
    """Return canonical JSON filename for ``item_id``."""

    return f"{int(item_id)}.json"
