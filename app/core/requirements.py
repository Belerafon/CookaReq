"""High-level operations on requirement files.

This module centralizes business logic for loading, searching and
modifying requirements. It is used by CLI, MCP tools and can be reused by
GUI components.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from ..util.time import local_now_str, normalize_timestamp
from . import search as core_search
from .label_repository import FileLabelRepository, LabelRepository
from .labels import Label
from .model import Requirement, Status, requirement_from_dict
from .store import (
    delete,
    filename_for,
    load,
    load_index,
    save,
)

# Re-export searchable fields for UI components
SEARCHABLE_FIELDS = core_search.SEARCHABLE_FIELDS

def load_all(directory: str | Path) -> list[Requirement]:
    """Load all requirements from *directory*.

    Raises :class:`FileNotFoundError` if the directory does not exist.
    """
    path = Path(directory)
    if not path.is_dir():
        raise FileNotFoundError(str(directory))
    reqs: list[Requirement] = []
    for req_id in sorted(load_index(path)):
        data, _ = load(path / filename_for(req_id))
        reqs.append(requirement_from_dict(data))
    return reqs


def filter_by_status(
    requirements: Iterable[Requirement], status: str | Status | None
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


def search_requirements(
    directory: str | Path,
    *,
    query: str | None = None,
    labels: Sequence[str] | None = None,
    fields: Sequence[str] | None = None,
    status: str | None = None,
) -> list[Requirement]:
    """Load and filter requirements from *directory*.

    ``labels`` and ``query`` parameters mirror :func:`core.search.search`.
    ``status`` performs additional filtering before the search step.
    """
    reqs = load_all(directory)
    reqs = filter_by_status(reqs, status)
    return core_search.search(reqs, labels=list(labels or []), query=query, fields=fields)


def load_requirement(directory: str | Path, req_id: int) -> tuple[dict, float]:
    """Return raw requirement data and mtime for ``req_id``.

    Raises :class:`FileNotFoundError` when either the directory or file does not
    exist.
    """
    path = Path(directory)
    if not path.is_dir():
        raise FileNotFoundError(str(directory))
    return load(path / filename_for(req_id))


def get_requirement(directory: str | Path, req_id: int) -> Requirement:
    """Return :class:`Requirement` with ``req_id`` from ``directory``."""
    data, _ = load_requirement(directory, req_id)
    return requirement_from_dict(data)


def save_requirement(
    directory: str | Path,
    data: Mapping | Requirement,
    *,
    mtime: float | None = None,
    modified_at: str | None = None,
):
    """Persist ``data`` as requirement in ``directory`` and return file path."""
    if isinstance(data, Requirement):
        obj = data
    else:
        obj = requirement_from_dict(dict(data))
    obj.modified_at = (
        normalize_timestamp(modified_at) if modified_at else local_now_str()
    )
    return save(directory, obj, mtime=mtime)


def delete_requirement(directory: str | Path, req_id: int) -> None:
    """Remove requirement ``req_id`` from ``directory``."""
    delete(directory, req_id)


def list_ids(directory: str | Path) -> set[int]:
    """Return set of requirement ids present in ``directory``."""
    return set(load_index(directory))


def search_loaded(
    requirements: Iterable[Requirement],
    *,
    labels: Sequence[str] | None = None,
    query: str | None = None,
    fields: Sequence[str] | None = None,
    field_queries: Mapping[str, str] | None = None,
    match_all: bool = True,
    is_derived: bool = False,
    has_derived: bool = False,
    suspect_only: bool = False,
) -> list[Requirement]:
    """Filter ``requirements`` in memory using search criteria."""
    return core_search.search(
        requirements,
        labels=labels,
        query=query,
        fields=fields,
        field_queries=field_queries,
        match_all=match_all,
        is_derived=is_derived,
        has_derived=has_derived,
        suspect_only=suspect_only,
    )


def load_labels(
    directory: str | Path, repo: LabelRepository | None = None
) -> list[Label]:
    """Load labels from ``directory`` using ``repo`` if provided."""
    repo = repo or FileLabelRepository()
    return repo.load(directory)


def save_labels(
    directory: str | Path, labels: list[Label], repo: LabelRepository | None = None
):
    """Persist ``labels`` into ``directory`` using ``repo`` if provided."""
    repo = repo or FileLabelRepository()
    return repo.save(directory, labels)
