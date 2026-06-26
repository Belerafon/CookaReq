import json
from pathlib import Path

import pytest

from app.core.trace_index.parse_code import parse_code_file, parse_code_text

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "trace_index_project"


@pytest.mark.unit
def test_parse_code_marker_single_rid() -> None:
    result = parse_code_text("void f(void) {\n    /* @covers LLR3 */\n}\n", path="Vsrc/demo.c")

    assert result.issues == ()
    assert len(result.code_locations) == 1
    location = result.code_locations[0]
    assert location.rid == "LLR3"
    assert location.line_start == 2
    assert location.line_end == 2
    assert location.marker_text == "@covers LLR3"
    assert location.stable_key == "Vsrc/demo.c::LLR3::marker-0001"


@pytest.mark.unit
def test_parse_code_marker_multiple_rids_with_note_and_symbol() -> None:
    result = parse_code_text(
        "int demo_step(int value) {\n"
        "    /* @covers LLR1, LLR2: clamp and diagnostics */\n"
        "    return value;\n"
        "}\n",
        path="Vsrc/demo.c",
    )

    assert result.issues == ()
    assert [location.rid for location in result.code_locations] == ["LLR1", "LLR2"]
    assert {location.symbol for location in result.code_locations} == {"demo_step"}
    assert {location.marker_ordinal for location in result.code_locations} == {1}


@pytest.mark.unit
def test_parse_code_marker_invalid_rid_produces_issue() -> None:
    result = parse_code_text("/* @covers llr3 */\n", path="Vsrc/demo.c")

    assert result.code_locations == ()
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.code == "INVALID_MARKER"
    assert issue.severity == "high"
    assert issue.line == 1


@pytest.mark.unit
def test_parse_code_ignores_covers_marker_inside_string_literal() -> None:
    result = parse_code_text(
        'const char *text = "/* @covers LLR3 */";\n', path="Vsrc/demo.c"
    )

    assert result.code_locations == ()
    assert result.issues == ()


@pytest.mark.unit
def test_parse_code_line_number_changes_do_not_change_stable_key() -> None:
    first = parse_code_text("/* @covers LLR3 */\n", path="Vsrc/demo.c")
    shifted = parse_code_text("\n\n/* @covers LLR3: note */\n", path="Vsrc/demo.c")

    assert first.code_locations[0].line_start == 1
    assert shifted.code_locations[0].line_start == 3
    assert first.code_locations[0].stable_key == shifted.code_locations[0].stable_key


@pytest.mark.unit
def test_trace_index_project_fixture_code_locations_match_expected() -> None:
    result = parse_code_file(FIXTURE_ROOT / "Vsrc" / "demo.c", project_root=FIXTURE_ROOT)
    expected = json.loads(
        (FIXTURE_ROOT / "expected" / "code_locations.json").read_text(encoding="utf-8")
    )

    assert result.issues == ()
    assert [location.to_dict() for location in result.code_locations] == expected


@pytest.mark.unit
def test_trace_index_project_fixture_broken_marker_issues_match_expected() -> None:
    result = parse_code_file(
        FIXTURE_ROOT / "Vsrc" / "broken_marker.c", project_root=FIXTURE_ROOT
    )
    expected = json.loads(
        (FIXTURE_ROOT / "expected" / "broken_code_issues.json").read_text(
            encoding="utf-8"
        )
    )

    assert result.code_locations == ()
    assert [issue.to_dict() for issue in result.issues] == expected
