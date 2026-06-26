import json
from pathlib import Path

import pytest

from app.core.trace_index.parse_tests import parse_test_file, parse_test_text

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "trace_index_project"


@pytest.mark.unit
def test_parse_print_case_header_with_static_id() -> None:
    result = parse_test_text(
        'static const char ID[] = "ТЕСТ-UT-DEMO-0001";\n'
        'print_case_header(ID, "LLR3", "Clamp output");\n',
        path="tests/test_demo/src/test_demo.c",
    )

    assert result.issues == ()
    assert len(result.test_cases) == 1
    test_case = result.test_cases[0]
    assert test_case.test_id == "ТЕСТ-UT-DEMO-0001"
    assert test_case.covers == ("LLR3",)
    assert test_case.line_start == 2
    assert test_case.stable_key == "ТЕСТ-UT-DEMO-0001"


@pytest.mark.unit
def test_parse_print_case_header_with_direct_string_id() -> None:
    result = parse_test_text(
        'print_case_header("ТЕСТ-UT-DEMO-0002", "LLR4", "Diagnostics");\n',
        path="tests/test_demo/src/test_demo.c",
    )

    assert result.issues == ()
    assert len(result.test_cases) == 1
    assert result.test_cases[0].test_id == "ТЕСТ-UT-DEMO-0002"
    assert result.test_cases[0].covers == ("LLR4",)


@pytest.mark.unit
def test_parse_explicit_test_marker_with_multiple_rids() -> None:
    result = parse_test_text(
        "/* @test ТЕСТ-UT-DEMO-0003 @covers LLR1, LLR2: demo note */\n",
        path="tests/test_demo/src/test_demo.c",
    )

    assert result.issues == ()
    assert len(result.test_cases) == 1
    assert result.test_cases[0].test_id == "ТЕСТ-UT-DEMO-0003"
    assert result.test_cases[0].covers == ("LLR1", "LLR2")


@pytest.mark.unit
def test_parse_test_markers_with_same_sources_are_deduplicated() -> None:
    result = parse_test_text(
        '/* @test ТЕСТ-UT-DEMO-0004 @covers LLR5 */\n'
        'static const char ID[] = "ТЕСТ-UT-DEMO-0004";\n'
        'print_case_header(ID, "LLR5", "Same coverage");\n',
        path="tests/test_demo/src/test_demo.c",
    )

    assert result.issues == ()
    assert len(result.test_cases) == 1
    assert result.test_cases[0].test_id == "ТЕСТ-UT-DEMO-0004"
    assert result.test_cases[0].covers == ("LLR5",)


@pytest.mark.unit
def test_parse_test_marker_conflict_produces_issue() -> None:
    result = parse_test_text(
        '/* @test ТЕСТ-UT-DEMO-0005 @covers LLR5 */\n'
        'static const char ID[] = "ТЕСТ-UT-DEMO-0005";\n'
        'print_case_header(ID, "LLR6", "Different coverage");\n',
        path="tests/test_demo/src/test_demo.c",
    )

    assert result.test_cases == ()
    assert len(result.issues) == 1
    assert result.issues[0].code == "CONFLICTING_TEST_MARKERS"
    assert result.issues[0].severity == "high"
    assert result.issues[0].test_id == "ТЕСТ-UT-DEMO-0005"


@pytest.mark.unit
def test_parse_duplicate_test_id_produces_issue() -> None:
    result = parse_test_text(
        'print_case_header("ТЕСТ-UT-DEMO-0006", "LLR7", "First");\n'
        'print_case_header("ТЕСТ-UT-DEMO-0006", "LLR7", "Second");\n',
        path="tests/test_demo/src/test_demo.c",
    )

    assert len(result.test_cases) == 1
    assert len(result.issues) == 1
    assert result.issues[0].code == "DUPLICATE_TEST_ID"
    assert result.issues[0].severity == "high"


@pytest.mark.unit
def test_parse_print_case_header_macro_args_produce_invalid_marker_issue() -> None:
    result = parse_test_text(
        'print_case_header(TEST_ID, LLR_ID, "Macro args are not expanded");\n',
        path="tests/test_demo/src/test_demo.c",
    )

    assert result.test_cases == ()
    assert len(result.issues) == 1
    assert result.issues[0].code == "INVALID_MARKER"


@pytest.mark.unit
def test_trace_index_project_fixture_test_cases_match_expected() -> None:
    result = parse_test_file(
        FIXTURE_ROOT / "tests" / "test_demo" / "src" / "test_demo.c",
        project_root=FIXTURE_ROOT,
    )
    expected = json.loads(
        (FIXTURE_ROOT / "expected" / "test_cases.json").read_text(encoding="utf-8")
    )

    assert result.issues == ()
    assert [test_case.to_dict() for test_case in result.test_cases] == expected
