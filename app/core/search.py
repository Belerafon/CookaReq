"""In-memory search helpers for requirements."""
from __future__ import annotations

from typing import Iterable, List, Sequence, Any

from .model import Requirement

# Fields allowed for text search
SEARCHABLE_FIELDS = {
    "title",
    "statement",
    "acceptance",
    "source",
    "owner",
    "notes",
}

def _get_attr(obj: Any, name: str, default: Any = None) -> Any:
    """Return attribute or dict value ``name`` from ``obj``.

    Supports both dataclass instances and plain dictionaries. If ``name`` is
    missing, ``default`` is returned.
    """
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def filter_by_labels(
    requirements: Iterable[Requirement | dict],
    labels: Sequence[str],
) -> List[Requirement | dict]:
    """Return requirements containing all of the given labels.

    Empty ``labels`` yields all requirements unchanged.
    """
    reqs = list(requirements)
    if not labels:
        return reqs
    label_set = set(labels)
    return [r for r in reqs if label_set.issubset(set(_get_attr(r, "labels", [])))]

def search_text(
    requirements: Iterable[Requirement | dict],
    query: str,
    fields: Sequence[str],
) -> List[Requirement | dict]:
    """Perform case-insensitive text search over selected fields.

    ``fields`` outside of :data:`SEARCHABLE_FIELDS` are ignored. If no ``fields``
    remain or ``query`` is empty, the original list is returned.
    """
    reqs = list(requirements)
    if not query:
        return reqs
    fields = [f for f in fields if f in SEARCHABLE_FIELDS]
    if not fields:
        return reqs
    q = query.lower()
    result: List[Requirement | dict] = []
    for r in reqs:
        for field in fields:
            value = _get_attr(r, field, None)
            if value and q in str(value).lower():
                result.append(r)
                break
    return result

def search(
    requirements: Iterable[Requirement | dict],
    *,
    labels: Sequence[str] | None = None,
    query: str | None = None,
    fields: Sequence[str] | None = None,
) -> List[Requirement | dict]:
    """Filter requirements by ``labels`` and ``query`` across ``fields``.

    ``fields`` defaults to :data:`SEARCHABLE_FIELDS` when ``query`` is provided.
    """
    reqs = filter_by_labels(requirements, labels or [])
    if query:
        reqs = search_text(reqs, query, fields or list(SEARCHABLE_FIELDS))
    return reqs
