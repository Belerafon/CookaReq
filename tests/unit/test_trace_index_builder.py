import json
from pathlib import Path

import pytest

from app.core.trace_index.builder import build_trace_index
from app.core.trace_index.config import TraceIndexConfig

FIXTURE_ROOT = Path("tests/fixtures/trace_index_project")


def _without_volatile(index_dict: dict) -> dict:
    result = dict(index_dict)
    result["generated_at_utc"] = "<volatile>"
    return result


@pytest.mark.unit
def test_build_trace_index_matches_golden_fixture() -> None:
    config = TraceIndexConfig.from_conventions(
        FIXTURE_ROOT / "Req",
        project_root=FIXTURE_ROOT,
        exclude_globs=("Vsrc/broken_*",),
    )

    index = build_trace_index(config)
    expected = json.loads(
        (FIXTURE_ROOT / "expected" / "trace_index.generated.json").read_text(
            encoding="utf-8"
        )
    )

    assert _without_volatile(index.to_dict()) == expected


@pytest.mark.unit
def test_build_trace_index_reports_unknown_code_marker_rid() -> None:
    config = TraceIndexConfig.from_conventions(
        FIXTURE_ROOT / "Req",
        project_root=FIXTURE_ROOT,
        source_globs=("Vsrc/broken_marker.c",),
        test_globs=(),
        result_globs=(),
    )

    index = build_trace_index(config)

    assert any(issue.code == "INVALID_MARKER" for issue in index.issues)
    assert any(issue.code == "MISSING_TEST_FOR_LLR" and issue.rid == "LLR1" for issue in index.issues)


@pytest.mark.unit
def test_build_trace_index_reports_unknown_test_case_rid(tmp_path: Path) -> None:
    _write_minimal_req(tmp_path, verification="inspection")
    test_dir = tmp_path / "tests" / "test_demo" / "src"
    test_dir.mkdir(parents=True)
    (test_dir / "test_demo.c").write_text(
        'print_case_header("TEST-1", "LLR99", "Unknown");\n', encoding="utf-8"
    )
    config = TraceIndexConfig.from_conventions(tmp_path / "Req", project_root=tmp_path)

    index = build_trace_index(config)

    assert any(issue.code == "UNKNOWN_RID" and issue.rid == "LLR99" for issue in index.issues)


@pytest.mark.unit
def test_build_trace_index_reports_result_without_test_case(tmp_path: Path) -> None:
    _write_minimal_req(tmp_path, verification="inspection")
    result_dir = tmp_path / "tests" / "test_demo" / "Build"
    result_dir.mkdir(parents=True)
    (result_dir / "test_results.txt").write_text(
        "ИД_ПРОГОНА: RUN-1; ОКРУЖЕНИЕ: HOST; ДАТА_UTC: 2026-05-26T00:00:00Z\n"
        "ИДЕНТ_ТЕСТА: TEST-1\n"
        "ПОКРЫВАЕТ_ТНУ: LLR1\n"
        "РЕЗУЛЬТАТ: TEST-1 = ПРОШЕЛ\n",
        encoding="utf-8",
    )
    config = TraceIndexConfig.from_conventions(tmp_path / "Req", project_root=tmp_path)

    index = build_trace_index(config)

    assert any(issue.code == "RESULT_WITHOUT_TEST_CASE" for issue in index.issues)


@pytest.mark.unit
def test_build_trace_index_reports_coverage_mismatch(tmp_path: Path) -> None:
    _write_minimal_req(tmp_path, verification="inspection")
    _write_req_item(tmp_path, item_id=2, verification="inspection")
    test_dir = tmp_path / "tests" / "test_demo" / "src"
    test_dir.mkdir(parents=True)
    (test_dir / "test_demo.c").write_text(
        'print_case_header("TEST-1", "LLR1", "Source coverage");\n', encoding="utf-8"
    )
    result_dir = tmp_path / "tests" / "test_demo" / "Build"
    result_dir.mkdir(parents=True)
    (result_dir / "test_results.txt").write_text(
        "ИД_ПРОГОНА: RUN-1; ОКРУЖЕНИЕ: HOST; ДАТА_UTC: 2026-05-26T00:00:00Z\n"
        "ИДЕНТ_ТЕСТА: TEST-1\n"
        "ПОКРЫВАЕТ_ТНУ: LLR2\n"
        "РЕЗУЛЬТАТ: TEST-1 = ПРОШЕЛ\n",
        encoding="utf-8",
    )
    config = TraceIndexConfig.from_conventions(tmp_path / "Req", project_root=tmp_path)

    index = build_trace_index(config)

    assert any(issue.code == "COVERAGE_MISMATCH" for issue in index.issues)


@pytest.mark.unit
def test_build_trace_index_normalizes_rid_spelling_variants(tmp_path: Path) -> None:
    _write_minimal_req(tmp_path, verification="test")
    source_dir = tmp_path / "Vsrc"
    source_dir.mkdir()
    (source_dir / "pid.c").write_text(
        "void pid(void)\n"
        "{\n"
        "    /* @covers LLR001, LLR-1: accepted spelling variants */\n"
        "}\n",
        encoding="utf-8",
    )
    test_dir = tmp_path / "tests" / "test_pid" / "src"
    test_dir.mkdir(parents=True)
    (test_dir / "test_pid.c").write_text(
        'print_case_header("TEST-PID-1", "LLR1, LLR-001", "PID");\n',
        encoding="utf-8",
    )

    config = TraceIndexConfig.from_conventions(tmp_path / "Req", project_root=tmp_path)

    index = build_trace_index(config)

    assert index.issues == ()
    assert {location.rid for location in index.code_locations} == {"LLR1"}
    assert index.test_cases[0].covers == ("LLR1",)


@pytest.mark.unit
def test_build_trace_index_discovers_junit_xml_result_by_default(tmp_path: Path) -> None:
    _write_minimal_req(tmp_path, verification="test")
    test_dir = tmp_path / "tests" / "test_demo" / "src"
    test_dir.mkdir(parents=True)
    (test_dir / "test_demo.c").write_text(
        'print_case_header("TEST-JUNIT-1", "LLR1", "JUnit");\n',
        encoding="utf-8",
    )
    result_dir = tmp_path / "tests" / "test_demo" / "Build"
    result_dir.mkdir(parents=True)
    (result_dir / "junit.xml").write_text(
        """<testsuite name="suite">
  <properties><property name="run_id" value="RUN-JUNIT-1" /></properties>
  <testcase name="TEST-JUNIT-1">
    <properties><property name="covers" value="LLR1" /></properties>
  </testcase>
</testsuite>
""",
        encoding="utf-8",
    )

    config = TraceIndexConfig.from_conventions(tmp_path / "Req", project_root=tmp_path)

    index = build_trace_index(config)

    assert index.issues == ()
    assert [run.run_id for run in index.test_runs] == ["RUN-JUNIT-1"]
    assert [result.test_id for result in index.test_results] == ["TEST-JUNIT-1"]
    assert index.test_results[0].normalized_status == "passed"
    assert index.test_results[0].covers == ("LLR1",)


def _write_minimal_req(tmp_path: Path, *, verification: str) -> None:
    (tmp_path / "Req" / "LLR" / "items").mkdir(parents=True)
    (tmp_path / "Req" / "LLR" / "document.json").write_text(
        '{"prefix": "LLR", "title": "Low"}\n', encoding="utf-8"
    )
    _write_req_item(tmp_path, item_id=1, verification=verification)


def _write_req_item(tmp_path: Path, *, item_id: int, verification: str) -> None:
    (tmp_path / "Req" / "LLR" / "items" / f"{item_id}.json").write_text(
        json.dumps(
            {
                "id": item_id,
                "title": f"Requirement {item_id}",
                "statement": "Statement",
                "verification": verification,
                "verification_methods": [verification],
                "links": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
