import json
from pathlib import Path

import pytest

from app.core.trace_index.parse_results import (
    normalize_status,
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
