"""In-memory search helpers for requirements."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

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


def filter_is_derived(
    requirements: Iterable[Requirement],
    *,
    suspect_only: bool = False,
) -> list[Requirement]:
    """Return only requirements that are derived from others.

    When ``suspect_only`` is ``True`` keep only requirements that have at least
    one suspect derivation link.
    """

    reqs = [r for r in requirements if r.derived_from]
    if suspect_only:
        reqs = [r for r in reqs if any(link.suspect for link in r.derived_from)]
    return reqs


def filter_has_derived(
    requirements: Iterable[Requirement],
    all_requirements: Iterable[Requirement],
    *,
    suspect_only: bool = False,
) -> list[Requirement]:
    """Return requirements that act as sources for derivations.

    ``all_requirements`` is used to inspect derivation links from every
    requirement, ensuring that sources are identified even if derived
    requirements are filtered out before this call. When ``suspect_only`` is
    ``True`` a requirement is returned only if at least one of its derived
    requirements links to it with ``suspect`` set.
    """

    reqs = list(requirements)
    sources: dict[int, list[bool]] = {}
    for req in all_requirements:
        for link in req.derived_from:
            sources.setdefault(link.source_id, []).append(link.suspect)

    result: list[Requirement] = []
    for req in reqs:
        flags = sources.get(req.id, [])
        if not flags:
            continue
        if suspect_only and not any(flags):
            continue
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
    suspect_only: bool = False,
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
        reqs = filter_is_derived(reqs, suspect_only=suspect_only)
    if has_derived:
        reqs = filter_has_derived(reqs, all_reqs, suspect_only=suspect_only)
    return reqs
