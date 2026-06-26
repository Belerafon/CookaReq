"""Parser for C/C++ block-comment ``@covers`` trace markers."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .model import CodeLocation, TraceIssue
from .parsers import (
    RID_RE,
    display_path,
    iter_block_comments,
    rid_list_candidate,
    rid_list_is_valid,
)

_COVERS_RE = re.compile(r"@covers\s+([^@\r\n*]+)")
_FUNCTION_RE = re.compile(
    r"^\s*(?:[A-Za-z_][\w\s\*]*\s+)+(?P<name>[A-Za-z_]\w*)\s*\([^;]*\)\s*\{\s*$"
)


@dataclass(frozen=True)
class CodeParseResult:
    """Result of scanning one source file for code coverage markers."""

    code_locations: tuple[CodeLocation, ...] = ()
    issues: tuple[TraceIssue, ...] = ()


def parse_code_file(path: str | Path, *, project_root: str | Path | None = None) -> CodeParseResult:
    """Read and parse a C source/header file for block-comment ``@covers`` markers."""
    source_path = Path(path)
    path_text = display_path(source_path, project_root)
    try:
        text = source_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return CodeParseResult(
            issues=(
                TraceIssue(
                    code="INPUT_FILE_UNREADABLE",
                    severity="high",
                    message=f"Cannot read source file: {exc}",
                    path=path_text,
                ),
            )
        )
    return parse_code_text(text, path=path_text)


def parse_code_text(text: str, *, path: str) -> CodeParseResult:
    """Parse C source text for MVP block-comment ``@covers`` markers."""
    comments = tuple(iter_block_comments(text))
    symbol_by_line = _symbol_lookup(text)
    locations: list[CodeLocation] = []
    issues: list[TraceIssue] = []
    marker_ordinal = 0

    for comment_text, line_start, line_end in comments:
        for match in _COVERS_RE.finditer(comment_text):
            marker_ordinal += 1
            marker_text = match.group(0).strip()
            rid_text = rid_list_candidate(match.group(1))
            rids = tuple(RID_RE.findall(rid_text))
            if not rids or not rid_list_is_valid(rid_text, rids):
                issues.append(
                    TraceIssue(
                        code="INVALID_MARKER",
                        severity="high",
                        message="Invalid @covers marker RID list",
                        path=path,
                        line=line_start,
                    )
                )
                continue
            symbol = symbol_by_line.get(line_start)
            for rid in rids:
                locations.append(
                    CodeLocation(
                        rid=rid,
                        path=path,
                        line_start=line_start,
                        line_end=line_end,
                        marker_text=marker_text,
                        marker_ordinal=marker_ordinal,
                        symbol=symbol,
                    )
                )

    return CodeParseResult(code_locations=tuple(locations), issues=tuple(issues))


def _symbol_lookup(text: str) -> dict[int, str | None]:
    lookup: dict[int, str | None] = {}
    current_symbol: str | None = None
    depth = 0
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        if depth == 0:
            match = _FUNCTION_RE.match(raw_line)
            if match:
                current_symbol = match.group("name")
        lookup[line_number] = current_symbol
        depth += raw_line.count("{") - raw_line.count("}")
        if depth <= 0:
            depth = 0
            if "}" in raw_line:
                current_symbol = None
    return lookup
