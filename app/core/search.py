"""In-memory search helpers for requirements."""
from __future__ import annotations

from typing import Iterable, List, Sequence

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
 
def filter_by_labels(
    requirements: Iterable[Requirement],
    labels: Sequence[str],
    *,
    match_all: bool = True,
) -> List[Requirement]:
    """Return requirements matching ``labels``.

    By default all ``labels`` must be present in a requirement. When
    ``match_all`` is ``False`` a requirement is kept if it has at least one of
    the requested labels. Empty ``labels`` yields all requirements unchanged.
    """
    reqs = list(requirements)
    if not labels:
        return reqs
    label_set = set(labels)
    if match_all:
        return [r for r in reqs if label_set.issubset(set(r.labels))]
    return [r for r in reqs if set(r.labels) & label_set]


def search_text(
    requirements: Iterable[Requirement],
    query: str,
    fields: Sequence[str],
) -> List[Requirement]:
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
    result: List[Requirement] = []
    for r in reqs:
        for field in fields:
            value = getattr(r, field, None)
            if value and q in str(value).lower():
                result.append(r)
                break
    return result


def search(
    requirements: Iterable[Requirement],
    *,
    labels: Sequence[str] | None = None,
    query: str | None = None,
    fields: Sequence[str] | None = None,
    match_all: bool = True,
) -> List[Requirement]:
    """Filter requirements by ``labels`` and ``query`` across ``fields``.

    ``fields`` defaults to :data:`SEARCHABLE_FIELDS` when ``query`` is provided.
    ``match_all`` controls whether all ``labels`` must be present or any of them
    is sufficient.
    """
    reqs = filter_by_labels(requirements, labels or [], match_all=match_all)
    if query:
        reqs = search_text(reqs, query, fields or list(SEARCHABLE_FIELDS))
    return reqs
