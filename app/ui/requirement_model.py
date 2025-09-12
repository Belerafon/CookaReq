"""Model managing requirements data with filtering and sorting."""
from __future__ import annotations

from typing import List, Sequence, Any

from app.core import search as core_search


class RequirementModel:
    """Maintain requirement data and apply filters/sorting."""

    def __init__(self) -> None:
        self._all: List[dict] = []
        self._visible: List[dict] = []
        self._labels: List[str] = []
        self._labels_match_all: bool = True
        self._query: str = ""
        self._fields: Sequence[str] | None = None
        self._sort_field: str | None = None
        self._sort_ascending: bool = True

    # data management -------------------------------------------------
    def set_requirements(self, requirements: List[dict]) -> None:
        """Replace all requirements."""
        self._all = list(requirements)
        self._refresh()

    def add(self, requirement: dict) -> None:
        self._all.append(requirement)
        self._refresh()

    def update(self, requirement: dict) -> None:
        rid = requirement.get("id")
        for i, req in enumerate(self._all):
            if req.get("id") == rid:
                self._all[i] = requirement
                break
        else:  # not found
            self._all.append(requirement)
        self._refresh()

    def delete(self, req_id: int) -> None:
        self._all = [r for r in self._all if r.get("id") != req_id]
        self._refresh()

    def get_by_id(self, req_id: int) -> dict | None:
        for req in self._all:
            if req.get("id") == req_id:
                return req
        return None

    # filtering -------------------------------------------------------
    def set_label_filter(self, labels: List[str]) -> None:
        self._labels = labels
        self._refresh()

    def set_label_match_all(self, match_all: bool) -> None:
        self._labels_match_all = match_all
        self._refresh()

    def set_search_query(self, query: str, fields: Sequence[str] | None = None) -> None:
        self._query = query
        self._fields = fields
        self._refresh()

    # sorting ---------------------------------------------------------
    def sort(self, field: str, ascending: bool = True) -> None:
        self._sort_field = field
        self._sort_ascending = ascending
        self._apply_sort()

    # helpers ---------------------------------------------------------
    def _refresh(self) -> None:
        self._visible = core_search.search(
            self._all,
            labels=self._labels,
            query=self._query,
            fields=self._fields,
            match_all=self._labels_match_all,
        )
        self._apply_sort()

    def _apply_sort(self) -> None:
        if not self._sort_field:
            return

        def get_value(req: Any):
            value = req.get(self._sort_field, "")
            if self._sort_field == "id":
                try:
                    return int(value)
                except Exception:
                    return 0
            if self._sort_field == "labels" and isinstance(value, list):
                # учитываем все метки, чтобы корректно сравнивать несколько
                return "|".join(value)
            return value

        self._visible.sort(key=get_value, reverse=not self._sort_ascending)

    # access ----------------------------------------------------------
    def get_visible(self) -> List[dict]:
        return list(self._visible)

    def get_all(self) -> List[dict]:
        return list(self._all)
