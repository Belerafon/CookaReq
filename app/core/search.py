"""In-memory search helpers for requirements."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from .model import Requirement, Status

# Fields allowed for text search
SEARCHABLE_FIELDS = {
    "title",
    "statement",
    "acceptance",
    "source",
    "owner",
    "notes",
    "rationale",
    "assumptions",
}


def filter_by_status(
    requirements: Iterable[Requirement],
    status: str | Status | None,
) -> list[Requirement]:
    """Filter ``requirements`` by ``status`` if provided."""
    reqs = list(requirements)
    if not status:
        return reqs
    try:
        st = Status(status)
    except ValueError:
        return []
    return [r for r in reqs if r.status == st]


def filter_by_labels(
    requirements: Iterable[Requirement],
    labels: Sequence[str],
    *,
    match_all: bool = True,
) -> list[Requirement]:
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
) -> list[Requirement]:
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
    result: list[Requirement] = []
    for r in reqs:
        for field in fields:
            value = getattr(r, field, None)
            if value and q in str(value).lower():
                result.append(r)
                break
    return result


def filter_text_fields(
    requirements: Iterable[Requirement],
    queries: Mapping[str, str],
) -> list[Requirement]:
    """Filter requirements by individual field queries.

    ``queries`` maps field names to case-insensitive substrings that must be
    present in the corresponding field. Fields outside of
    :data:`SEARCHABLE_FIELDS` or empty query strings are ignored. A requirement
    must satisfy *all* provided field queries to be included in the result.
    """
    reqs = list(requirements)
    if not queries:
        return reqs
    for field, query in queries.items():
        if not query or field not in SEARCHABLE_FIELDS:
            continue
        q = query.lower()
        reqs = [r for r in reqs if q in str(getattr(r, field, "")).lower()]
    return reqs


def filter_is_derived(requirements: Iterable[Requirement]) -> list[Requirement]:
    """Return only requirements that link to other requirements."""
    return [r for r in requirements if getattr(r, "links", [])]


def filter_has_derived(
    requirements: Iterable[Requirement],
    all_requirements: Iterable[Requirement],
) -> list[Requirement]:
    """Return requirements that are referenced by other requirements."""
    reqs = list(requirements)
    sources: set[str] = set()
    for req in all_requirements:
        for parent in getattr(req, "links", []):
            parent_rid = getattr(parent, "rid", parent)
            sources.add(str(parent_rid))

    result: list[Requirement] = []
    for req in reqs:
        rid = req.rid or str(req.id)
        if rid in sources:
            result.append(req)
    return result


def search(
    requirements: Iterable[Requirement],
    *,
    labels: Sequence[str] | None = None,
    query: str | None = None,
    fields: Sequence[str] | None = None,
    match_all: bool = True,
    is_derived: bool = False,
    has_derived: bool = False,
    field_queries: Mapping[str, str] | None = None,
) -> list[Requirement]:
    """Filter requirements by ``labels`` and ``query`` across ``fields``.

    ``fields`` defaults to :data:`SEARCHABLE_FIELDS` when ``query`` is provided.
    ``match_all`` controls whether all ``labels`` must be present or any of them
    is sufficient.
    """
    all_reqs = list(requirements)
    reqs = filter_by_labels(all_reqs, labels or [], match_all=match_all)
    if query:
        reqs = search_text(reqs, query, fields or list(SEARCHABLE_FIELDS))
    if field_queries:
        reqs = filter_text_fields(reqs, field_queries)
    if is_derived:
        reqs = filter_is_derived(reqs)
    if has_derived:
        reqs = filter_has_derived(reqs, all_reqs)
    return reqs
