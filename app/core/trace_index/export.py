"""Export helpers for external evidence trace-index reports."""
from __future__ import annotations

import csv
import html
from io import StringIO

from .matrix import TraceArtifactMatrix, TraceArtifactMatrixCell
from .model import TraceIndex


def render_artifact_matrix_csv(matrix: TraceArtifactMatrix) -> str:
    """Render an artifact trace matrix as CSV text."""
    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(_headers(matrix))
    writer.writerows(_rows(matrix))
    return output.getvalue()


def render_artifact_matrix_html(matrix: TraceArtifactMatrix) -> str:
    """Render an artifact trace matrix as a standalone HTML table."""
    lines = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>Trace Index Artifact Matrix</title>",
        "<style>",
        "table { border-collapse: collapse; width: 100%; }",
        "th, td { border: 1px solid #ccc; padding: 0.25rem 0.5rem; text-align: left; }",
        "th { background: #f5f5f5; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>Trace Index Artifact Matrix</h1>",
        "<table>",
        "<thead>",
        _html_row("th", _headers(matrix)),
        "</thead>",
        "<tbody>",
    ]
    lines.extend(_html_row("td", row) for row in _rows(matrix))
    lines.extend(["</tbody>", "</table>", "</body>", "</html>"])
    return "\n".join(lines) + "\n"


def render_trace_index_report_html(
    index: TraceIndex,
    matrix: TraceArtifactMatrix,
) -> str:
    """Render a standalone HTML report for a TraceIndex and artifact matrix."""
    issue_rows = [
        [
            issue.severity,
            issue.code,
            issue.path,
            "" if issue.line is None else str(issue.line),
            issue.rid or "",
            issue.test_id or "",
            issue.message,
        ]
        for issue in index.issues
    ]
    lines = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        "<title>Trace Index Report</title>",
        "<style>",
        "body { font-family: sans-serif; }",
        "table { border-collapse: collapse; width: 100%; margin-bottom: 1rem; }",
        "th, td { border: 1px solid #ccc; padding: 0.25rem 0.5rem; text-align: left; }",
        "th { background: #f5f5f5; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>Trace Index Report</h1>",
        "<h2>Summary</h2>",
        "<table>",
        "<tbody>",
        _html_row("td", ["Requirements", str(len(index.requirements))]),
        _html_row("td", ["Code locations", str(len(index.code_locations))]),
        _html_row("td", ["Test cases", str(len(index.test_cases))]),
        _html_row("td", ["Test runs", str(len(index.test_runs))]),
        _html_row("td", ["Test results", str(len(index.test_results))]),
        _html_row("td", ["Issues", str(len(index.issues))]),
        "</tbody>",
        "</table>",
        "<h2>Diagnostics</h2>",
        "<table>",
        "<thead>",
        _html_row(
            "th",
            ["Severity", "Code", "Path", "Line", "RID", "Test ID", "Message"],
        ),
        "</thead>",
        "<tbody>",
    ]
    if issue_rows:
        lines.extend(_html_row("td", row) for row in issue_rows)
    else:
        lines.append(_html_row("td", ["", "", "", "", "", "", "No diagnostics"]))
    lines.extend(
        [
            "</tbody>",
            "</table>",
            "<h2>Artifact Matrix</h2>",
            "<table>",
            "<thead>",
            _html_row("th", _headers(matrix)),
            "</thead>",
            "<tbody>",
        ]
    )
    lines.extend(_html_row("td", row) for row in _rows(matrix))
    lines.extend(["</tbody>", "</table>", "</body>", "</html>"])
    return "\n".join(lines) + "\n"


def _headers(matrix: TraceArtifactMatrix) -> list[str]:
    return ["Requirement", "Title"] + [
        f"{column.kind}: {column.label}" for column in matrix.columns
    ]


def _rows(matrix: TraceArtifactMatrix) -> list[list[str]]:
    cells_by_rid: dict[str, dict[str, TraceArtifactMatrixCell]] = {}
    for cell in matrix.cells:
        cells_by_rid.setdefault(cell.rid, {})[cell.column_id] = cell
    rows: list[list[str]] = []
    for requirement in matrix.requirements:
        row = [requirement.rid, requirement.title]
        requirement_cells = cells_by_rid.get(requirement.rid, {})
        for column in matrix.columns:
            cell = requirement_cells.get(column.column_id)
            row.append(_cell_text(cell) if cell is not None else "")
        rows.append(row)
    return rows


def _cell_text(cell: TraceArtifactMatrixCell) -> str:
    if cell.marker == "test_result" and cell.status:
        return cell.status
    return cell.marker


def _html_row(tag: str, cells: list[str]) -> str:
    escaped = "".join(f"<{tag}>{html.escape(cell)}</{tag}>" for cell in cells)
    return f"<tr>{escaped}</tr>"
