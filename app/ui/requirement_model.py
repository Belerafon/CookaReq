"""Model managing requirements data with filtering and sorting."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum

from ..core import requirements as req_ops
from ..core.model import Requirement


class RequirementModel:
    """Maintain requirement data and apply filters/sorting."""

    def __init__(self) -> None:
        """Initialize empty requirement collections."""
        self._all: list[Requirement] = []
        self._visible: list[Requirement] = []
        self._labels: list[str] = []
        self._labels_match_all: bool = True
        self._query: str = ""
        self._fields: Sequence[str] | None = None
        self._field_queries: dict[str, str] = {}
        self._is_derived: bool = False
        self._has_derived: bool = False
        self._suspect_only: bool = False
        self._status: str | None = None
        self._sort_field: str | None = None
        self._sort_ascending: bool = True

    # data management -------------------------------------------------
    def set_requirements(self, requirements: list[Requirement]) -> None:
        """Replace all requirements."""
        self._all = list(requirements)
        self._refresh()

    def add(self, requirement: Requirement) -> None:
        """Append ``requirement`` to the model."""

        self._all.append(requirement)
        self._refresh()

    def update(self, requirement: Requirement) -> None:
        """Replace existing requirement with same id or append new."""

        rid = requirement.id
        for i, req in enumerate(self._all):
            if req.id == rid:
                self._all[i] = requirement
                break
        else:  # not found
            self._all.append(requirement)
        self._refresh()

    def delete(self, req_id: int) -> None:
        """Remove requirement with ``req_id``."""

        self._all = [r for r in self._all if r.id != req_id]
        self._refresh()

    def get_by_id(self, req_id: int) -> Requirement | None:
        """Return requirement with ``req_id`` or ``None``."""

        for req in self._all:
            if req.id == req_id:
                return req
        return None

    # filtering -------------------------------------------------------
    def set_label_filter(self, labels: list[str]) -> None:
        """Filter visible requirements by ``labels``."""

        self._labels = labels
        self._refresh()

    def set_label_match_all(self, match_all: bool) -> None:
        """Require all selected labels when ``match_all`` is ``True``."""

        self._labels_match_all = match_all
        self._refresh()

    def set_search_query(self, query: str, fields: Sequence[str] | None = None) -> None:
        """Set free-text ``query`` and optional fields to search."""

        self._query = query
        self._fields = fields
        self._refresh()

    def set_is_derived(self, value: bool) -> None:
        """Filter to requirements that are themselves derived."""

        self._is_derived = value
        self._refresh()

    def set_has_derived(self, value: bool) -> None:
        """Filter to requirements that have derived children."""

        self._has_derived = value
        self._refresh()

    def set_suspect_only(self, value: bool) -> None:
        """Restrict to requirements marked as suspect."""

        self._suspect_only = value
        self._refresh()

    def set_status(self, status: str | None) -> None:
        """Filter requirements by status code."""

        self._status = status
        self._refresh()

    def set_field_queries(self, queries: dict[str, str]) -> None:
        """Set per-field text filters."""
        self._field_queries = queries
        self._refresh()

    # sorting ---------------------------------------------------------
    def sort(self, field: str, ascending: bool = True) -> None:
        """Sort visible requirements by ``field``."""

        self._sort_field = field
        self._sort_ascending = ascending
        self._apply_sort()

    # helpers ---------------------------------------------------------
    def _refresh(self) -> None:
        base = req_ops.filter_by_status(self._all, self._status)
        self._visible = req_ops.search_loaded(
            base,
            labels=self._labels,
            query=self._query,
            fields=self._fields,
            field_queries=self._field_queries,
            match_all=self._labels_match_all,
            is_derived=self._is_derived,
            has_derived=self._has_derived,
            suspect_only=self._suspect_only,
        )
        self._apply_sort()

    def _apply_sort(self) -> None:
        if not self._sort_field:
            return

        def get_value(req: Requirement):
            value = getattr(req, self._sort_field, "")
            if isinstance(value, Enum):
                value = value.value
            if self._sort_field == "id":
                try:
                    return int(value)
                except Exception:
                    return 0
            if self._sort_field == "labels" and isinstance(value, list):
                return "|".join(value)
            if isinstance(value, list):
                return "|".join(str(v) for v in value)
            if is_dataclass(value):
                return str(asdict(value))
            return value

        self._visible.sort(key=get_value, reverse=not self._sort_ascending)

    # access ----------------------------------------------------------
    def get_visible(self) -> list[Requirement]:
        """Return currently visible requirements."""

        return list(self._visible)

    def get_all(self) -> list[Requirement]:
        """Return all requirements managed by the model."""

        return list(self._all)
