"""Utility functions for MCP requirement access."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from app.log import logger
from app.core import store
from app.core.model import Requirement, Status, requirement_from_dict, requirement_to_dict
from app.core import search as core_search


def _load_all(directory: str | Path) -> list[Requirement]:
    """Load all requirements from *directory* as :class:`Requirement` objects."""
    path = Path(directory)
    reqs: list[Requirement] = []
    for req_id in sorted(store.load_index(path)):
        fp = path / store.filename_for(req_id)
        try:
            data, _ = store.load(fp)
            reqs.append(requirement_from_dict(data))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to load %s: %s", fp, exc)
    return reqs


def _filter_status(requirements: Iterable[Requirement], status: str | None) -> list[Requirement]:
    reqs = list(requirements)
    if not status:
        return reqs
    try:
        st = Status(status)
    except ValueError:
        return []
    return [r for r in reqs if r.status == st]


def _paginate(requirements: Sequence[Requirement], page: int, per_page: int) -> dict:
    if page < 1:
        page = 1
    if per_page < 1:
        per_page = 1
    total = len(requirements)
    start = (page - 1) * per_page
    end = start + per_page
    items = [requirement_to_dict(r) for r in requirements[start:end]]
    return {"total": total, "page": page, "per_page": per_page, "items": items}


def list_requirements(
    directory: str | Path,
    *,
    page: int = 1,
    per_page: int = 50,
    status: str | None = None,
    tags: Sequence[str] | None = None,
) -> dict:
    """Return requirements from ``directory`` with optional filters."""
    reqs = _load_all(directory)
    reqs = _filter_status(reqs, status)
    if tags:
        reqs = core_search.filter_by_labels(reqs, list(tags))
    return _paginate(reqs, page, per_page)


def get_requirement(directory: str | Path, req_id: int) -> dict:
    """Return requirement ``req_id`` from ``directory``."""
    path = Path(directory) / store.filename_for(req_id)
    data, _ = store.load(path)
    req = requirement_from_dict(data)
    return requirement_to_dict(req)


def search_requirements(
    directory: str | Path,
    *,
    query: str | None = None,
    tags: Sequence[str] | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Search requirements with text query and optional filters."""
    reqs = _load_all(directory)
    reqs = _filter_status(reqs, status)
    reqs = core_search.search(reqs, labels=list(tags or []), query=query)
    return _paginate(reqs, page, per_page)
