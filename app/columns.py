"""Column selection utilities for requirements list views."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import fields
from types import MappingProxyType

from .core.model import Requirement

# Columns exposed via the View → Columns menu and persisted in UI settings.
# ``title`` is always shown and therefore excluded from the toggleable list.
_BASE_EXCLUDES = {"title", "labels"}
_EXTRA_COLUMNS = ("labels", "derived_from", "derived_count")


def _build_available_columns() -> list[str]:
    names = [
        field.name for field in fields(Requirement) if field.name not in _BASE_EXCLUDES
    ]
    for extra in _EXTRA_COLUMNS:
        if extra not in names:
            names.append(extra)
    return names


AVAILABLE_COLUMNS: tuple[str, ...] = tuple(_build_available_columns())
_AVAILABLE_COLUMN_SET = set(AVAILABLE_COLUMNS)

DEFAULT_LIST_COLUMNS: tuple[str, ...] = tuple(
    name
    for name in (
        "labels",
        "id",
        "source",
        "status",
        "priority",
        "type",
        "owner",
    )
    if name in _AVAILABLE_COLUMN_SET
)


DEFAULT_COLUMN_WIDTH = 160
_DEFAULT_COLUMN_WIDTHS: dict[str, int] = {
    "title": 400,
    "labels": 200,
    "id": 50,
    "source": 101,
    "status": 146,
    "priority": 86,
    "type": 150,
    "owner": 180,
    "doc_prefix": 140,
    "rid": 150,
    "derived_count": 120,
    "derived_from": 260,
    "modified_at": 180,
}
DEFAULT_COLUMN_WIDTHS = MappingProxyType(_DEFAULT_COLUMN_WIDTHS)


def available_columns() -> list[str]:
    """Return toggleable columns for requirement lists."""
    return list(AVAILABLE_COLUMNS)


def sanitize_columns(columns: Sequence[str]) -> list[str]:
    """Filter ``columns`` to valid, unique entries preserving order."""
    seen: set[str] = set()
    sanitized: list[str] = []
    for name in columns:
        if name in _AVAILABLE_COLUMN_SET and name not in seen:
            sanitized.append(name)
            seen.add(name)
    return sanitized


def default_column_width(field: str) -> int:
    """Return a sensible default width for ``field`` in requirement lists."""
    width = _DEFAULT_COLUMN_WIDTHS.get(field)
    if width is not None:
        return width
    if field.endswith("_at"):
        return 180
    if field in {"revision", "id", "doc_prefix", "derived_count"}:
        return 90
    return DEFAULT_COLUMN_WIDTH
