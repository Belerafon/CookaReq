"""Helpers for rendering tabular requirement exports."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import csv
import html
from io import StringIO

__all__ = [
    "render_tabular_delimited",
    "render_tabular_html",
    "render_tabular_txt",
]


def _normalize_cell(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\t", "\\t")
    return normalized.replace("\n", "\\n")


def render_tabular_txt(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> str:
    """Render tabular export as tab-separated text."""
    lines = ["\t".join(_normalize_cell(str(header)) for header in headers)]
    for row in rows:
        lines.append("\t".join(_normalize_cell(str(cell)) for cell in row))
    return "\n".join(lines) + "\n"


def render_tabular_delimited(
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    *,
    delimiter: str,
) -> str:
    """Render tabular export using CSV/TSV formatting."""
    buffer = StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    writer.writerow([str(header) for header in headers])
    for row in rows:
        writer.writerow([str(cell) for cell in row])
    return buffer.getvalue()


def _html_cell(value: str) -> str:
    escaped = html.escape(value)
    escaped = escaped.replace("\r\n", "\n").replace("\r", "\n")
    return escaped.replace("\n", "<br>")


def render_tabular_html(
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    *,
    title: str | None = None,
) -> str:
    """Render tabular export as standalone HTML."""
    heading = title or "Requirements export"
    parts = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>{html.escape(heading)}</title>",
        "<style>",
        "html{font-size:16px;-webkit-text-size-adjust:100%;text-size-adjust:100%;}",
        "body{font-family:Arial,Helvetica,sans-serif;margin:24px;font-size:0.875rem;line-height:1.4;}",
        "table{border-collapse:collapse;width:100%;font-size:inherit;}",
        "th,td{border:1px solid #ddd;padding:8px;vertical-align:top;font-size:inherit;}",
        "td *{font-size:inherit;}",
        "th{background:#f5f5f5;text-align:left;}",
        "</style>",
        "</head><body>",
        f"<h1>{html.escape(heading)}</h1>",
        "<table>",
        "<thead><tr>",
    ]
    for header in headers:
        parts.append(f"<th>{_html_cell(str(header))}</th>")
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        for cell in row:
            parts.append(f"<td>{_html_cell(str(cell))}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table></body></html>")
    return "".join(parts)
