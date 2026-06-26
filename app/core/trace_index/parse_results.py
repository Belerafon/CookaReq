"""Parser for legacy CookaReq text test result files."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .model import TestResultRef, TestRunRef, TraceIssue
from .parsers import RID_RE, display_path, rid_list_candidate, rid_list_is_valid

_RESULT_RE = re.compile(r"^РЕЗУЛЬТАТ:\s*(?:(?P<test_id>.+?)\s*=\s*)?(?P<status>\S+)\s*$")
_RUN_FIELD_RE = re.compile(r"\s*([^:;]+):\s*([^;]+)\s*")


@dataclass(frozen=True)
class ResultParseResult:
    """Result of scanning one legacy text test result file."""

    test_runs: tuple[TestRunRef, ...] = ()
    test_results: tuple[TestResultRef, ...] = ()
    issues: tuple[TraceIssue, ...] = ()


def parse_result_file(
    path: str | Path, *, project_root: str | Path | None = None
) -> ResultParseResult:
    """Read and parse a legacy text test result file."""
    result_path = Path(path)
    path_text = display_path(result_path, project_root)
    try:
        text = result_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return ResultParseResult(
            issues=(
                TraceIssue(
                    code="INPUT_FILE_UNREADABLE",
                    severity="high",
                    message=f"Cannot read test result file: {exc}",
                    path=path_text,
                ),
            )
        )
    return parse_result_text(text, result_file=path_text)


def parse_result_text(text: str, *, result_file: str) -> ResultParseResult:
    """Parse legacy test result text into test runs, results and issues."""
    parser = _LegacyResultParser(text, result_file)
    parser.parse()
    return ResultParseResult(
        test_runs=tuple(parser.test_runs),
        test_results=tuple(parser.test_results),
        issues=tuple(parser.issues),
    )


class _LegacyResultParser:
    def __init__(self, text: str, result_file: str) -> None:
        self.lines = text.splitlines()
        self.result_file = result_file
        self.current_run = TestRunRef(run_id="", result_file=result_file)
        self.test_runs: list[TestRunRef] = []
        self.test_results: list[TestResultRef] = []
        self.issues: list[TraceIssue] = []
        self.block_ordinal = 0
        self.current_block: _ResultBlock | None = None

    def parse(self) -> None:
        for line_number, line in enumerate(self.lines, start=1):
            if line.startswith("ИД_ПРОГОНА:"):
                self._finish_block(line_number - 1)
                self._start_run(line, line_number)
            elif line.startswith("ИДЕНТ_ТЕСТА:"):
                self._finish_block(line_number - 1)
                test_id = line.split(":", 1)[1].strip()
                if not test_id:
                    self.issues.append(
                        TraceIssue(
                            code="RESULT_WITHOUT_TEST_ID",
                            severity="high",
                            message="Result block does not contain a test id",
                            path=self.result_file,
                            line=line_number,
                        )
                    )
                    self.current_block = None
                    continue
                self.current_block = _ResultBlock(test_id=test_id, line_start=line_number)
            elif self.current_block is not None:
                self._read_block_line(line, line_number)
            elif line.startswith("РЕЗУЛЬТАТ:"):
                self.issues.append(
                    TraceIssue(
                        code="RESULT_WITHOUT_TEST_ID",
                        severity="high",
                        message="Result line is not associated with a test id",
                        path=self.result_file,
                        line=line_number,
                    )
                )
        self._finish_block(len(self.lines))

    def _start_run(self, line: str, line_number: int) -> None:
        fields = _parse_run_fields(line)
        run_id = fields.get("ИД_ПРОГОНА", "")
        if not run_id:
            self.issues.append(
                TraceIssue(
                    code="RESULT_WITHOUT_TEST_ID",
                    severity="high",
                    message="Run header does not contain a run id",
                    path=self.result_file,
                    line=line_number,
                )
            )
            return
        self.current_run = TestRunRef(
            run_id=run_id,
            result_file=self.result_file,
            env=fields.get("ОКРУЖЕНИЕ", ""),
            date_utc=fields.get("ДАТА_UTC", ""),
        )
        if self.current_run.stable_key not in {run.stable_key for run in self.test_runs}:
            self.test_runs.append(self.current_run)

    def _read_block_line(self, line: str, line_number: int) -> None:
        block = self.current_block
        if block is None:
            return
        if line.startswith("ПОКРЫВАЕТ_ТНУ:"):
            covers_text = rid_list_candidate(line.split(":", 1)[1].strip())
            covers = tuple(RID_RE.findall(covers_text))
            if covers and rid_list_is_valid(covers_text, covers):
                block.covers = covers
            else:
                self.issues.append(
                    TraceIssue(
                        code="INVALID_MARKER",
                        severity="high",
                        message="Invalid result coverage RID list",
                        path=self.result_file,
                        line=line_number,
                        test_id=block.test_id,
                    )
                )
        elif line.startswith("ОЖИДАЕМОЕ:"):
            block.expected = line.split(":", 1)[1].strip()
        elif line.startswith("КРИТЕРИЙ:"):
            block.criterion = line.split(":", 1)[1].strip()
        elif line.startswith("РЕЗУЛЬТАТ:"):
            self._read_result_line(block, line, line_number)
        elif line.strip():
            block.diagnostics.append(line)

    def _read_result_line(self, block: _ResultBlock, line: str, line_number: int) -> None:
        match = _RESULT_RE.match(line.strip())
        if not match:
            self.issues.append(
                TraceIssue(
                    code="INVALID_MARKER",
                    severity="high",
                    message="Invalid result status line",
                    path=self.result_file,
                    line=line_number,
                    test_id=block.test_id,
                )
            )
            return
        result_test_id = (match.group("test_id") or "").strip()
        if result_test_id and result_test_id != block.test_id:
            self.issues.append(
                TraceIssue(
                    code="RESULT_TEST_ID_MISMATCH",
                    severity="high",
                    message="Result status test id differs from block test id",
                    path=self.result_file,
                    line=line_number,
                    test_id=block.test_id,
                )
            )
        block.raw_status = match.group("status").strip()
        block.normalized_status = normalize_status(block.raw_status)
        block.line_end = line_number
        self._finish_block(line_number)

    def _finish_block(self, line_end: int) -> None:
        block = self.current_block
        if block is None:
            return
        if block.raw_status:
            self.block_ordinal += 1
            self.test_results.append(
                TestResultRef(
                    run_id=self.current_run.run_id,
                    test_id=block.test_id,
                    result_file=self.result_file,
                    block_ordinal=self.block_ordinal,
                    raw_status=block.raw_status,
                    normalized_status=block.normalized_status,
                    covers=block.covers,
                    expected=block.expected,
                    criterion=block.criterion,
                    diagnostics=tuple(block.diagnostics),
                    line_start=block.line_start,
                    line_end=block.line_end or line_end,
                )
            )
        self.current_block = None


@dataclass
class _ResultBlock:
    test_id: str
    line_start: int
    covers: tuple[str, ...] = ()
    expected: str = ""
    criterion: str = ""
    diagnostics: list[str] | None = None
    raw_status: str = ""
    normalized_status: str = "unknown"
    line_end: int | None = None

    def __post_init__(self) -> None:
        if self.diagnostics is None:
            self.diagnostics = []


def _parse_run_fields(line: str) -> dict[str, str]:
    body = line.strip()
    fields: dict[str, str] = {}
    for part in body.split(";"):
        match = _RUN_FIELD_RE.match(part)
        if match:
            fields[match.group(1).strip()] = match.group(2).strip()
    return fields


def normalize_status(raw_status: str) -> str:
    """Normalize raw legacy result status text."""
    normalized = raw_status.strip().upper()
    if normalized in {"ПРОШЕЛ", "PASSED", "PASS", "OK"}:
        return "passed"
    if normalized in {"НЕ_ПРОШЕЛ", "FAILED", "FAIL", "FAILURE"}:
        return "failed"
    if normalized in {"ОШИБКА", "ERROR"}:
        return "error"
    if normalized in {"ПРОПУЩЕН", "SKIPPED", "SKIP"}:
        return "skipped"
    return "unknown"
