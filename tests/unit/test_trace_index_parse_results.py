import json
from pathlib import Path

import pytest

from app.core.trace_index.parse_results import (
    normalize_status,
    parse_junit_result_text,
    parse_result_file,
    parse_result_text,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "trace_index_project"


@pytest.mark.unit
def test_parse_run_header() -> None:
    result = parse_result_text(
        "ИД_ПРОГОНА: RUN-1; ОКРУЖЕНИЕ: HOST; ДАТА_UTC: 2026-05-26T00:00:00Z\n",
        result_file="out.txt",
    )

    assert len(result.test_runs) == 1
    run = result.test_runs[0]
    assert run.run_id == "RUN-1"
    assert run.env == "HOST"
    assert run.date_utc == "2026-05-26T00:00:00Z"


@pytest.mark.unit
def test_parse_test_result_block() -> None:
    result = parse_result_text(
        "ИД_ПРОГОНА: RUN-1; ОКРУЖЕНИЕ: HOST; ДАТА_UTC: 2026-05-26T00:00:00Z\n"
        "ИДЕНТ_ТЕСТА: ТЕСТ-1\n"
        "ПОКРЫВАЕТ_ТНУ: LLR1, LLR2\n"
        "ОЖИДАЕМОЕ: expected text\n"
        "КРИТЕРИЙ: criterion text\n"
        "[LOG] diagnostic text\n"
        "РЕЗУЛЬТАТ: ТЕСТ-1 = ПРОШЕЛ\n",
        result_file="out.txt",
    )

    assert result.issues == ()
    assert len(result.test_results) == 1
    test_result = result.test_results[0]
    assert test_result.test_id == "ТЕСТ-1"
    assert test_result.covers == ("LLR1", "LLR2")
    assert test_result.expected == "expected text"
    assert test_result.criterion == "criterion text"
    assert test_result.diagnostics == ("[LOG] diagnostic text",)
    assert test_result.raw_status == "ПРОШЕЛ"
    assert test_result.normalized_status == "passed"
    assert test_result.line_start == 2
    assert test_result.line_end == 7


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        ("ПРОШЕЛ", "passed"),
        ("НЕ_ПРОШЕЛ", "failed"),
        ("ОШИБКА", "error"),
        ("SKIPPED", "skipped"),
        ("SOMETHING_ELSE", "unknown"),
    ],
)
def test_normalize_status(raw_status: str, expected: str) -> None:
    assert normalize_status(raw_status) == expected


@pytest.mark.unit
def test_parse_multiple_results_and_ignore_summary() -> None:
    result = parse_result_text(
        "ИД_ПРОГОНА: RUN-1; ОКРУЖЕНИЕ: HOST; ДАТА_UTC: 2026-05-26T00:00:00Z\n"
        "ИДЕНТ_ТЕСТА: ТЕСТ-1\n"
        "РЕЗУЛЬТАТ: ТЕСТ-1 = ПРОШЕЛ\n"
        "ИДЕНТ_ТЕСТА: ТЕСТ-2\n"
        "РЕЗУЛЬТАТ: ТЕСТ-2 = НЕ_ПРОШЕЛ\n"
        "ИТОГО: 2\n"
        "ПРОШЛО: 1\n"
        "НЕ ПРОШЛО: 1\n",
        result_file="out.txt",
    )

    assert result.issues == ()
    assert [item.test_id for item in result.test_results] == ["ТЕСТ-1", "ТЕСТ-2"]
    assert [item.normalized_status for item in result.test_results] == ["passed", "failed"]


@pytest.mark.unit
def test_result_without_test_id_produces_issue() -> None:
    result = parse_result_text("РЕЗУЛЬТАТ: ТЕСТ-1 = ПРОШЕЛ\n", result_file="out.txt")

    assert result.test_results == ()
    assert len(result.issues) == 1
    assert result.issues[0].code == "RESULT_WITHOUT_TEST_ID"
    assert result.issues[0].severity == "high"


@pytest.mark.unit
def test_result_test_id_mismatch_produces_issue_but_keeps_result() -> None:
    result = parse_result_text(
        "ИД_ПРОГОНА: RUN-1; ОКРУЖЕНИЕ: HOST; ДАТА_UTC: 2026-05-26T00:00:00Z\n"
        "ИДЕНТ_ТЕСТА: ТЕСТ-1\n"
        "РЕЗУЛЬТАТ: ТЕСТ-2 = ПРОШЕЛ\n",
        result_file="out.txt",
    )

    assert len(result.test_results) == 1
    assert len(result.issues) == 1
    assert result.issues[0].code == "RESULT_TEST_ID_MISMATCH"
    assert result.issues[0].test_id == "ТЕСТ-1"


@pytest.mark.unit
def test_trace_index_project_fixture_results_match_expected() -> None:
    result = parse_result_file(
        FIXTURE_ROOT / "tests" / "test_demo" / "Build" / "test_results.txt",
        project_root=FIXTURE_ROOT,
    )
    expected_runs = json.loads(
        (FIXTURE_ROOT / "expected" / "test_runs.json").read_text(encoding="utf-8")
    )
    expected_results = json.loads(
        (FIXTURE_ROOT / "expected" / "test_results.json").read_text(encoding="utf-8")
    )

    assert result.issues == ()
    assert [run.to_dict() for run in result.test_runs] == expected_runs
    assert [test_result.to_dict() for test_result in result.test_results] == expected_results


@pytest.mark.unit
def test_parse_junit_result_text_with_properties() -> None:
    result = parse_junit_result_text(
        """<?xml version="1.0" encoding="utf-8"?>
<testsuite name="suite" timestamp="2026-06-25T12:00:00Z">
  <properties>
    <property name="run_id" value="RUN-JUNIT-1" />
    <property name="env" value="CI" />
  </properties>
  <testcase classname="demo" name="test_pass">
    <properties>
      <property name="test_id" value="ТЕСТ-JUNIT-1" />
      <property name="covers" value="LLR1, LLR2" />
    </properties>
  </testcase>
  <testcase classname="demo" name="test_fail">
    <properties>
      <property name="test_id" value="ТЕСТ-JUNIT-2" />
      <property name="covers" value="LLR3" />
    </properties>
    <failure message="assert failed">stack</failure>
  </testcase>
</testsuite>
""",
        result_file="junit.xml",
    )

    assert result.issues == ()
    assert len(result.test_runs) == 1
    assert result.test_runs[0].run_id == "RUN-JUNIT-1"
    assert result.test_runs[0].env == "CI"
    assert result.test_runs[0].date_utc == "2026-06-25T12:00:00Z"
    assert [item.test_id for item in result.test_results] == [
        "ТЕСТ-JUNIT-1",
        "ТЕСТ-JUNIT-2",
    ]
    assert [item.covers for item in result.test_results] == [
        ("LLR1", "LLR2"),
        ("LLR3",),
    ]
    assert [item.normalized_status for item in result.test_results] == [
        "passed",
        "failed",
    ]
    assert result.test_results[1].diagnostics == ("assert failed",)


@pytest.mark.unit
def test_parse_result_file_dispatches_junit_xml(tmp_path: Path) -> None:
    path = tmp_path / "junit.xml"
    path.write_text(
        """<testsuite name="suite">
  <testcase classname="demo" name="test_error">
    <properties><property name="covers" value="LLR1" /></properties>
    <error message="boom" />
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )

    result = parse_result_file(path, project_root=tmp_path)

    assert result.issues == ()
    assert result.test_results[0].result_file == "junit.xml"
    assert result.test_results[0].test_id == "demo.test_error"
    assert result.test_results[0].normalized_status == "error"


@pytest.mark.unit
def test_parse_junit_result_text_reports_invalid_covers() -> None:
    result = parse_junit_result_text(
        """<testsuite name="suite">
  <testcase name="test_bad">
    <properties><property name="covers" value="LLR1; LLR2" /></properties>
  </testcase>
</testsuite>
""",
        result_file="junit.xml",
    )

    assert len(result.test_results) == 1
    assert result.test_results[0].covers == ()
    assert len(result.issues) == 1
    assert result.issues[0].code == "INVALID_MARKER"
    assert result.issues[0].test_id == "test_bad"
