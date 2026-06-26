"""Parser for C test-case evidence markers."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from .model import TestCaseRef, TraceIssue
from .parsers import (
    RID_RE,
    display_path,
    iter_block_comments,
    line_for_offset,
    rid_list_candidate,
    rid_list_is_valid,
)

_STATIC_ID_RE = re.compile(
    r"static\s+const\s+char\s+(?P<name>[A-Za-z_]\w*)\s*\[\s*\]\s*=\s*\"(?P<value>[^\"]+)\"\s*;"
)
_TEST_MARKER_RE = re.compile(
    r"@test\s+(?P<test_id>\S+)\s+@covers\s+(?P<covers>[^@\r\n*]+)"
)
_PRINT_HEADER_RE = re.compile(r"\bprint_case_header\s*\((?P<args>.*?)\)\s*;", re.DOTALL)
_STRING_RE = re.compile(r'^"(?P<value>(?:[^"\\]|\\.)*)"$')


@dataclass(frozen=True)
class TestParseResult:
    """Result of scanning one test source file for test-case references."""

    test_cases: tuple[TestCaseRef, ...] = ()
    issues: tuple[TraceIssue, ...] = ()


def parse_test_file(path: str | Path, *, project_root: str | Path | None = None) -> TestParseResult:
    """Read and parse a C test source file for test-case evidence markers."""
    source_path = Path(path)
    path_text = display_path(source_path, project_root)
    try:
        text = source_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return TestParseResult(
            issues=(
                TraceIssue(
                    code="INPUT_FILE_UNREADABLE",
                    severity="high",
                    message=f"Cannot read test source file: {exc}",
                    path=path_text,
                ),
            )
        )
    return parse_test_text(text, path=path_text)


def parse_test_text(text: str, *, path: str) -> TestParseResult:
    """Parse C test source text for explicit and legacy test markers."""
    candidates: list[TestCaseRef] = []
    issues: list[TraceIssue] = []
    candidates.extend(_explicit_marker_cases(text, path=path, issues=issues))
    candidates.extend(_print_header_cases(text, path=path, issues=issues))
    test_cases, duplicate_issues = _merge_candidates(candidates, path=path)
    issues.extend(duplicate_issues)
    return TestParseResult(test_cases=tuple(test_cases), issues=tuple(issues))


def _explicit_marker_cases(
    text: str, *, path: str, issues: list[TraceIssue]
) -> list[TestCaseRef]:
    cases: list[TestCaseRef] = []
    for comment, line_start, line_end in iter_block_comments(text):
        for match in _TEST_MARKER_RE.finditer(comment):
            test_id = match.group("test_id").strip()
            covers_text = rid_list_candidate(match.group("covers"))
            covers = tuple(RID_RE.findall(covers_text))
            if not test_id or not covers or not rid_list_is_valid(covers_text, covers):
                issues.append(
                    TraceIssue(
                        code="INVALID_MARKER",
                        severity="high",
                        message="Invalid @test marker",
                        path=path,
                        line=line_start,
                        test_id=test_id or None,
                    )
                )
                continue
            cases.append(
                TestCaseRef(
                    test_id=test_id,
                    path=path,
                    line_start=line_start,
                    line_end=line_end,
                    covers=covers,
                    marker_text=match.group(0).strip(),
                )
            )
    return cases


def _print_header_cases(
    text: str, *, path: str, issues: list[TraceIssue]
) -> list[TestCaseRef]:
    cases: list[TestCaseRef] = []
    id_values = _static_id_values(text)
    for match in _PRINT_HEADER_RE.finditer(text):
        line = line_for_offset(text, match.start())
        args = _split_call_args(match.group("args"))
        if len(args) < 2:
            issues.append(_invalid_print_header(path, line, None))
            continue
        test_id = _resolve_string_or_id(args[0], id_values)
        covers = _resolve_covers_arg(args[1])
        if test_id is None:
            issues.append(_invalid_print_header(path, line, None))
            continue
        if covers is None:
            issues.append(_invalid_print_header(path, line, test_id))
            continue
        cases.append(
            TestCaseRef(
                test_id=test_id,
                path=path,
                line_start=line,
                line_end=line_for_offset(text, match.end()),
                covers=covers,
                marker_text=match.group(0).strip(),
            )
        )
    return cases


def _static_id_values(text: str) -> dict[str, str]:
    return {match.group("name"): match.group("value") for match in _STATIC_ID_RE.finditer(text)}


def _resolve_string_or_id(arg: str, id_values: dict[str, str]) -> str | None:
    stripped = arg.strip()
    string_value = _string_literal_value(stripped)
    if string_value is not None:
        return string_value
    return id_values.get(stripped)


def _resolve_covers_arg(arg: str) -> tuple[str, ...] | None:
    value = _string_literal_value(arg.strip())
    if value is None:
        return None
    covers_text = rid_list_candidate(value)
    covers = tuple(RID_RE.findall(covers_text))
    if not covers or not rid_list_is_valid(covers_text, covers):
        return None
    return covers


def _invalid_print_header(path: str, line: int, test_id: str | None) -> TraceIssue:
    return TraceIssue(
        code="INVALID_MARKER",
        severity="high",
        message="Invalid print_case_header marker",
        path=path,
        line=line,
        test_id=test_id,
    )


def _merge_candidates(
    candidates: list[TestCaseRef], *, path: str
) -> tuple[list[TestCaseRef], list[TraceIssue]]:
    by_id: dict[str, list[TestCaseRef]] = {}
    for candidate in candidates:
        by_id.setdefault(candidate.test_id, []).append(candidate)

    merged: list[TestCaseRef] = []
    issues: list[TraceIssue] = []
    for test_id in sorted(by_id):
        group = by_id[test_id]
        cover_sets = {case.covers for case in group}
        if len(cover_sets) > 1:
            issues.append(
                TraceIssue(
                    code="CONFLICTING_TEST_MARKERS",
                    severity="high",
                    message="Conflicting test markers for the same test_id",
                    path=path,
                    line=min(case.line_start for case in group),
                    test_id=test_id,
                )
            )
            continue
        if len(group) > 1 and len({case.path for case in group}) == 1:
            explicit_count = sum("@test" in case.marker_text for case in group)
            legacy_count = len(group) - explicit_count
            if explicit_count != 1 or legacy_count != 1:
                issues.append(
                    TraceIssue(
                        code="DUPLICATE_TEST_ID",
                        severity="high",
                        message="Duplicate test_id in test source",
                        path=path,
                        line=min(case.line_start for case in group),
                        test_id=test_id,
                    )
                )
        merged.append(sorted(group, key=lambda case: case.line_start)[0])
    return sorted(merged, key=lambda case: case.stable_key), issues


def _split_call_args(args: str) -> list[str]:
    result: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    i = 0
    while i < len(args):
        char = args[i]
        if quote:
            if char == "\\":
                i += 2
                continue
            if char == quote:
                quote = None
        elif char in {'"', "'"}:
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")" and depth > 0:
            depth -= 1
        elif char == "," and depth == 0:
            result.append(args[start:i].strip())
            start = i + 1
        i += 1
    result.append(args[start:].strip())
    return result


def _string_literal_value(value: str) -> str | None:
    if not _STRING_RE.match(value):
        return None
    try:
        literal = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return None
    return literal if isinstance(literal, str) else None

