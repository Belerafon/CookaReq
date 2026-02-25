"""Build traceability matrices from the requirement store."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from pathlib import Path
from collections.abc import Mapping, Sequence

from .document_store import (
    Document,
    DocumentNotFoundError,
    load_documents,
    load_requirements,
)
from .model import Link, Requirement, RequirementType, Status
from .search import SEARCHABLE_FIELDS, filter_text_fields, search_text


class TraceDirection(StrEnum):
    """Define orientation of links within the matrix."""

    CHILD_TO_PARENT = "child-to-parent"
    PARENT_TO_CHILD = "parent-to-child"


@dataclass(frozen=True)
class TraceMatrixAxisConfig:
    """Describe requirement selection for a matrix axis."""

    documents: tuple[str, ...] = ()
    include_descendants: bool = False
    statuses: tuple[Status | str, ...] = ()
    requirement_types: tuple[RequirementType | str, ...] = ()
    labels_all: tuple[str, ...] = ()
    labels_any: tuple[str, ...] = ()
    query: str = ""
    query_fields: tuple[str, ...] = ()
    field_queries: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TraceMatrixConfig:
    """Parameters required to build a traceability matrix."""

    rows: TraceMatrixAxisConfig
    columns: TraceMatrixAxisConfig
    direction: TraceDirection = TraceDirection.CHILD_TO_PARENT


@dataclass(frozen=True)
class TraceMatrixLinkView:
    """Normalized representation of a link within the matrix."""

    source_rid: str
    target_rid: str
    suspect: bool
    revision: int | None


@dataclass(frozen=True)
class TraceMatrixCell:
    """Cell payload containing one or more links."""

    links: tuple[TraceMatrixLinkView, ...]

    @property
    def suspect(self) -> bool:
        """Return ``True`` when at least one link in the cell is suspect."""
        return any(link.suspect for link in self.links)


@dataclass(frozen=True)
class TraceMatrixAxisEntry:
    """Materialized requirement used on a matrix axis."""

    requirement: Requirement
    document: Document

    @property
    def rid(self) -> str:
        """Return the requirement identifier used on this axis entry."""
        return self.requirement.rid


@dataclass(frozen=True)
class TraceMatrixSummary:
    """Aggregated coverage statistics for a matrix."""

    total_rows: int
    total_columns: int
    total_pairs: int
    linked_pairs: int
    link_count: int
    row_coverage: float
    column_coverage: float
    pair_coverage: float
    orphan_rows: tuple[str, ...]
    orphan_columns: tuple[str, ...]


@dataclass(frozen=True)
class TraceMatrix:
    """Computed traceability matrix with supporting metadata."""

    config: TraceMatrixConfig
    direction: TraceDirection
    rows: tuple[TraceMatrixAxisEntry, ...]
    columns: tuple[TraceMatrixAxisEntry, ...]
    cells: Mapping[tuple[str, str], TraceMatrixCell]
    summary: TraceMatrixSummary
    documents: Mapping[str, Document]


def build_trace_matrix(
    root: str | Path,
    config: TraceMatrixConfig,
    *,
    docs: Mapping[str, Document] | None = None,
) -> TraceMatrix:
    """Return a traceability matrix for ``config`` rooted at ``root``."""
    root_path = Path(root)
    docs_map = docs or load_documents(root_path)
    row_prefixes = _resolve_prefixes(config.rows, docs_map)
    column_prefixes = _resolve_prefixes(config.columns, docs_map)

    row_requirements = _load_axis_requirements(root_path, docs_map, row_prefixes, config.rows)
    column_requirements = _load_axis_requirements(root_path, docs_map, column_prefixes, config.columns)

    rows = _prepare_axis_entries(row_requirements, docs_map)
    columns = _prepare_axis_entries(column_requirements, docs_map)

    cells = _build_cells(rows, columns, config.direction)
    summary = _build_summary(rows, columns, cells)

    return TraceMatrix(
        config=config,
        direction=config.direction,
        rows=rows,
        columns=columns,
        cells=cells,
        summary=summary,
        documents=dict(docs_map),
    )


def _resolve_prefixes(axis: TraceMatrixAxisConfig, docs: Mapping[str, Document]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()

    def _visit(prefix: str) -> None:
        if prefix in seen:
            return
        if prefix not in docs:
            raise DocumentNotFoundError(prefix)
        seen.add(prefix)
        resolved.append(prefix)
        if not axis.include_descendants:
            return
        for child_prefix in sorted(docs):
            child = docs[child_prefix]
            if child.parent == prefix:
                _visit(child_prefix)

    for prefix in axis.documents:
        clean = prefix.strip()
        if not clean:
            continue
        _visit(clean)
    if not resolved:
        raise ValueError("TraceMatrixAxisConfig.documents cannot be empty")
    return resolved


def _load_axis_requirements(
    root: Path,
    docs: Mapping[str, Document],
    prefixes: Sequence[str],
    axis: TraceMatrixAxisConfig,
) -> list[Requirement]:
    requirements = load_requirements(root, prefixes=prefixes, docs=docs)
    return _filter_axis_requirements(requirements, axis)


def _normalize_enum_sequence(values: Sequence[Enum | str], enum_cls: type[Enum]) -> tuple[Enum, ...]:
    normalized: list[Enum] = []
    seen: set[Enum] = set()
    for raw in values:
        if isinstance(raw, enum_cls):
            candidate = raw
        elif isinstance(raw, str):
            candidate = _enum_from_string(enum_cls, raw)
            if candidate is None:
                raise ValueError(f"unknown {enum_cls.__name__}: {raw}")
        else:
            raise TypeError(f"unsupported {enum_cls.__name__} value: {raw!r}")
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return tuple(normalized)


def _enum_from_string(enum_cls: type[Enum], raw: str) -> Enum | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return enum_cls(text)
    except ValueError:
        try:
            return enum_cls(text.lower())
        except ValueError:
            return None


def _filter_axis_requirements(
    requirements: Sequence[Requirement], axis: TraceMatrixAxisConfig
) -> list[Requirement]:
    reqs = list(requirements)

    if axis.statuses:
        allowed_status = set(_normalize_enum_sequence(axis.statuses, Status))
        reqs = [req for req in reqs if req.status in allowed_status]

    if axis.requirement_types:
        allowed_types = set(
            _normalize_enum_sequence(axis.requirement_types, RequirementType)
        )
        reqs = [req for req in reqs if req.type in allowed_types]

    if axis.labels_all:
        required = {label.strip() for label in axis.labels_all if label.strip()}
        if required:
            reqs = [req for req in reqs if required.issubset(set(req.labels))]

    if axis.labels_any:
        candidates = {label.strip() for label in axis.labels_any if label.strip()}
        if candidates:
            reqs = [req for req in reqs if set(req.labels) & candidates]

    if axis.query:
        fields = axis.query_fields or tuple(SEARCHABLE_FIELDS)
        reqs = search_text(reqs, axis.query, fields)

    if axis.field_queries:
        reqs = filter_text_fields(reqs, axis.field_queries)

    return reqs


def _prepare_axis_entries(
    requirements: Sequence[Requirement], docs: Mapping[str, Document]
) -> tuple[TraceMatrixAxisEntry, ...]:
    entries: list[TraceMatrixAxisEntry] = []
    for req in requirements:
        doc = docs.get(req.doc_prefix)
        if doc is None:
            raise DocumentNotFoundError(req.doc_prefix)
        entries.append(TraceMatrixAxisEntry(requirement=req, document=doc))
    return tuple(entries)


def _build_cells(
    rows: Sequence[TraceMatrixAxisEntry],
    columns: Sequence[TraceMatrixAxisEntry],
    direction: TraceDirection,
) -> dict[tuple[str, str], TraceMatrixCell]:
    row_index = {entry.rid: entry for entry in rows}
    column_index = {entry.rid: entry for entry in columns}

    buckets: dict[tuple[str, str], list[TraceMatrixLinkView]] = {}

    if direction == TraceDirection.CHILD_TO_PARENT:
        for entry in rows:
            source_rid = entry.rid
            for raw_link in entry.requirement.links:
                if not isinstance(raw_link, Link):  # pragma: no cover - defensive
                    continue
                target_rid = getattr(raw_link, "rid", "").strip()
                if not target_rid or target_rid not in column_index:
                    continue
                key = (source_rid, target_rid)
                buckets.setdefault(key, []).append(
                    TraceMatrixLinkView(
                        source_rid=source_rid,
                        target_rid=target_rid,
                        suspect=raw_link.suspect,
                        revision=raw_link.revision,
                    )
                )
    else:
        for entry in columns:
            target_rid = entry.rid
            for raw_link in entry.requirement.links:
                if not isinstance(raw_link, Link):  # pragma: no cover - defensive
                    continue
                source_rid = getattr(raw_link, "rid", "").strip()
                if not source_rid or source_rid not in row_index:
                    continue
                key = (source_rid, target_rid)
                buckets.setdefault(key, []).append(
                    TraceMatrixLinkView(
                        source_rid=source_rid,
                        target_rid=target_rid,
                        suspect=raw_link.suspect,
                        revision=raw_link.revision,
                    )
                )

    cells: dict[tuple[str, str], TraceMatrixCell] = {}
    for key, values in buckets.items():
        ordered = sorted(
            values,
            key=lambda item: (
                item.source_rid,
                item.target_rid,
                item.revision or 0,
                item.suspect,
            ),
        )
        cells[key] = TraceMatrixCell(links=tuple(ordered))
    return cells


def _build_summary(
    rows: Sequence[TraceMatrixAxisEntry],
    columns: Sequence[TraceMatrixAxisEntry],
    cells: Mapping[tuple[str, str], TraceMatrixCell],
) -> TraceMatrixSummary:
    total_rows = len(rows)
    total_columns = len(columns)
    total_pairs = total_rows * total_columns
    linked_pairs = sum(1 for cell in cells.values() if cell.links)
    link_count = sum(len(cell.links) for cell in cells.values())

    linked_rows: set[str] = {key[0] for key, cell in cells.items() if cell.links}
    linked_columns: set[str] = {key[1] for key, cell in cells.items() if cell.links}

    row_coverage = (len(linked_rows) / total_rows) if total_rows else 0.0
    column_coverage = (len(linked_columns) / total_columns) if total_columns else 0.0
    pair_coverage = (linked_pairs / total_pairs) if total_pairs else 0.0

    orphan_rows = tuple(
        entry.rid for entry in rows if entry.rid not in linked_rows
    )
    orphan_columns = tuple(
        entry.rid for entry in columns if entry.rid not in linked_columns
    )

    return TraceMatrixSummary(
        total_rows=total_rows,
        total_columns=total_columns,
        total_pairs=total_pairs,
        linked_pairs=linked_pairs,
        link_count=link_count,
        row_coverage=row_coverage,
        column_coverage=column_coverage,
        pair_coverage=pair_coverage,
        orphan_rows=orphan_rows,
        orphan_columns=orphan_columns,
    )


__all__ = [
    "TraceDirection",
    "TraceMatrixAxisConfig",
    "TraceMatrixConfig",
    "TraceMatrix",
    "TraceMatrixCell",
    "TraceMatrixAxisEntry",
    "TraceMatrixLinkView",
    "TraceMatrixSummary",
    "build_trace_matrix",
]
