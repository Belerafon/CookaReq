"""Artifact trace matrix projections for external evidence TraceIndex data."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any

from .model import TraceIndex, TraceRequirementRef


@dataclass(frozen=True)
class TraceArtifactMatrixColumn:
    """One external evidence artifact column in a requirement trace matrix."""

    column_id: str
    kind: str
    label: str
    path: str
    line: int | None = None
    status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TraceArtifactMatrixCell:
    """One requirement-to-artifact coverage cell."""

    rid: str
    column_id: str
    marker: str
    status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TraceArtifactMatrix:
    """Requirement x external evidence artifact matrix."""

    requirements: tuple[TraceRequirementRef, ...]
    columns: tuple[TraceArtifactMatrixColumn, ...]
    cells: tuple[TraceArtifactMatrixCell, ...]

    def cells_for(self, rid: str) -> tuple[TraceArtifactMatrixCell, ...]:
        """Return all cells for one requirement RID."""
        return tuple(cell for cell in self.cells if cell.rid == rid)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirements": [requirement.to_dict() for requirement in self.requirements],
            "columns": [column.to_dict() for column in self.columns],
            "cells": [cell.to_dict() for cell in self.cells],
        }


def build_artifact_trace_matrix(index: TraceIndex) -> TraceArtifactMatrix:
    """Build a deterministic requirement x artifact matrix from ``index``."""
    requirement_rids = {requirement.rid for requirement in index.requirements}
    columns: list[TraceArtifactMatrixColumn] = []
    cells: list[TraceArtifactMatrixCell] = []

    for location in index.code_locations:
        column_id = f"code:{location.stable_key}"
        columns.append(
            TraceArtifactMatrixColumn(
                column_id=column_id,
                kind="code",
                label=_path_label(location.path, location.line_start),
                path=location.path,
                line=location.line_start,
            )
        )
        if location.rid in requirement_rids:
            cells.append(
                TraceArtifactMatrixCell(
                    rid=location.rid,
                    column_id=column_id,
                    marker="code",
                )
            )

    for test_case in index.test_cases:
        column_id = f"test_case:{test_case.stable_key}"
        columns.append(
            TraceArtifactMatrixColumn(
                column_id=column_id,
                kind="test_case",
                label=test_case.test_id,
                path=test_case.path,
                line=test_case.line_start,
            )
        )
        for rid in test_case.covers:
            if rid in requirement_rids:
                cells.append(
                    TraceArtifactMatrixCell(
                        rid=rid,
                        column_id=column_id,
                        marker="test_case",
                    )
                )

    for result in index.test_results:
        column_id = f"test_result:{result.stable_key}"
        columns.append(
            TraceArtifactMatrixColumn(
                column_id=column_id,
                kind="test_result",
                label=result.test_id,
                path=result.result_file,
                line=result.line_start,
                status=result.normalized_status,
            )
        )
        for rid in result.covers:
            if rid in requirement_rids:
                cells.append(
                    TraceArtifactMatrixCell(
                        rid=rid,
                        column_id=column_id,
                        marker="test_result",
                        status=result.normalized_status,
                    )
                )

    return TraceArtifactMatrix(
        requirements=tuple(sorted(index.requirements, key=lambda item: item.stable_key)),
        columns=tuple(sorted(columns, key=lambda item: (item.kind, item.column_id))),
        cells=tuple(sorted(cells, key=lambda item: (item.rid, item.column_id))),
    )


def _path_label(path: str, line: int | None) -> str:
    normalized = PurePosixPath(path).as_posix()
    return f"{normalized}:{line}" if line is not None else normalized
