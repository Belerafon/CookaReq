"""Sorting helpers for requirement exports."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .model import Requirement
from ..util.sorting import natural_sort_key

__all__ = ["sort_requirements_for_cards"]


def _labels_sort_key(labels: Sequence[str]) -> tuple[int, tuple[str, ...]]:
    normalized = tuple(sorted(label.strip().lower() for label in labels if label and label.strip()))
    if normalized:
        return (0, normalized)
    return (1, tuple())


def sort_requirements_for_cards(
    requirements: Iterable[Requirement],
    *,
    sort_mode: str,
) -> list[Requirement]:
    """Return requirements sorted for card-style exports.

    Supported ``sort_mode`` values:
    - ``id``: numeric requirement identifier.
    - ``labels``: lexicographic order of full labels set (requirements without labels last).
    - ``source``: source text, then requirement identifier.
    - ``title``: title text, then requirement identifier.
    """

    prepared = list(requirements)

    def key_by_id(requirement: Requirement) -> tuple[int]:
        return (requirement.id,)

    def key_by_labels(requirement: Requirement) -> tuple[int, tuple[str, ...], int]:
        marker, labels_key = _labels_sort_key(requirement.labels)
        return (marker, labels_key, requirement.id)

    def key_by_source(requirement: Requirement) -> tuple[object, int]:
        return (natural_sort_key(requirement.source), requirement.id)

    def key_by_title(requirement: Requirement) -> tuple[str, int]:
        return (requirement.title.strip().lower(), requirement.id)

    key_lookup = {
        "labels": key_by_labels,
        "source": key_by_source,
        "title": key_by_title,
        "id": key_by_id,
    }
    key_func = key_lookup.get(sort_mode, key_by_id)
    return sorted(prepared, key=key_func)
