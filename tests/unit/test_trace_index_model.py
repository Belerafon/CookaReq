import json

import pytest

from app.core.trace_index.model import (
    GENERATOR,
    SCHEMA_VERSION,
    CodeLocation,
    TestCaseRef,
    TestResultRef,
    TestRunRef,
    TraceIndex,
    TraceIssue,
    TraceRequirementRef,
    make_code_location_key,
)


@pytest.mark.unit
def test_trace_index_round_trips_to_json_without_data_loss() -> None:
    index = TraceIndex(
        project_root=".",
        req_root="Req",
        config_hash="cfg",
        input_fingerprint="fp",
        generated_at_utc="2026-06-25T00:00:00Z",
        requirements=(TraceRequirementRef(rid="LLR3", title="Demo", document="LLR"),),
        code_locations=(
            CodeLocation(
                rid="LLR3",
                path="Vsrc\\demo.c",
                line_start=10,
                line_end=10,
                marker_text="@covers LLR3",
                marker_ordinal=1,
                symbol="demo",
            ),
        ),
        test_cases=(
            TestCaseRef(
                test_id="ТЕСТ-UT-DEMO-0001",
                path="tests/test_demo/src/test_demo.c",
                line_start=20,
                line_end=20,
                covers=("LLR3",),
                marker_text='print_case_header(ID, "LLR3")',
            ),
        ),
        test_runs=(
            TestRunRef(
                run_id="ПРОГОН-1",
                result_file="tests/test_demo/Build/test_results.txt",
                env="HOST",
                date_utc="2026-05-26T00:00:00Z",
            ),
        ),
        test_results=(
            TestResultRef(
                run_id="ПРОГОН-1",
                test_id="ТЕСТ-UT-DEMO-0001",
                result_file="tests/test_demo/Build/test_results.txt",
                block_ordinal=1,
                raw_status="ПРОШЕЛ",
                normalized_status="passed",
                covers=("LLR3",),
            ),
        ),
        issues=(
            TraceIssue(
                code="RESULT_WITHOUT_COVERS",
                severity="warning",
                message="No covers in result",
                path="tests/test_demo/Build/test_results.txt",
                line=5,
                test_id="ТЕСТ-UT-DEMO-0001",
            ),
        ),
    )

    payload = json.loads(json.dumps(index.to_dict(), ensure_ascii=False))
    restored = TraceIndex.from_dict(payload)

    assert restored == index
    assert payload["generator"] == GENERATOR
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["code_locations"][0]["path"] == "Vsrc/demo.c"


@pytest.mark.unit
def test_stable_keys_are_independent_from_line_numbers_and_notes() -> None:
    first = CodeLocation(
        rid="LLR3",
        path="Vsrc/demo.c",
        line_start=10,
        line_end=10,
        marker_text="@covers LLR3: old note",
        marker_ordinal=2,
    )
    rescanned = CodeLocation(
        rid="LLR3",
        path="Vsrc/demo.c",
        line_start=99,
        line_end=99,
        marker_text="@covers LLR3: new note",
        marker_ordinal=2,
    )

    assert first.stable_key == rescanned.stable_key
    assert first.stable_key == make_code_location_key("Vsrc/demo.c", "LLR3", 2)
    assert TestCaseRef("TEST-1", "a.c", 1, 1).stable_key == "TEST-1"
    assert TestRunRef("RUN-1", "out.txt").stable_key == "RUN-1::out.txt"
    assert (
        TestResultRef("RUN-1", "TEST-1", "out.txt", 1, "ПРОШЕЛ", "passed").stable_key
        == "RUN-1::TEST-1::out.txt::block-0001"
    )


@pytest.mark.unit
def test_trace_index_top_level_schema_fields_and_entity_sorting() -> None:
    index = TraceIndex(
        project_root=".",
        req_root="Req",
        config_hash="cfg",
        input_fingerprint="fp",
        generated_at_utc="2026-06-25T00:00:00Z",
        requirements=(TraceRequirementRef("LLR2"), TraceRequirementRef("LLR1")),
        code_locations=(
            CodeLocation("LLR2", "b.c", 1, 1, "@covers LLR2", 1),
            CodeLocation("LLR1", "a.c", 1, 1, "@covers LLR1", 1),
        ),
        test_cases=(
            TestCaseRef("TEST-2", "b.c", 1, 1),
            TestCaseRef("TEST-1", "a.c", 1, 1),
        ),
        test_runs=(TestRunRef("RUN-2", "b.txt"), TestRunRef("RUN-1", "a.txt")),
        test_results=(
            TestResultRef("RUN-2", "TEST-2", "b.txt", 1, "ПРОШЕЛ", "passed"),
            TestResultRef("RUN-1", "TEST-1", "a.txt", 1, "ПРОШЕЛ", "passed"),
        ),
        issues=(
            TraceIssue("UNKNOWN_RID", "high", "Unknown", rid="LLR99"),
            TraceIssue("MODULE_NOT_FOUND", "warning", "Missing module"),
        ),
    )

    payload = index.to_dict()

    assert tuple(payload) == TraceIndex.TOP_LEVEL_FIELDS
    assert [item["rid"] for item in payload["requirements"]] == ["LLR1", "LLR2"]
    assert [item["stable_key"] for item in payload["code_locations"]] == [
        "a.c::LLR1::marker-0001",
        "b.c::LLR2::marker-0001",
    ]
    assert [item["test_id"] for item in payload["test_cases"]] == ["TEST-1", "TEST-2"]
    assert [item["run_id"] for item in payload["test_runs"]] == ["RUN-1", "RUN-2"]
    assert [item["test_id"] for item in payload["test_results"]] == ["TEST-1", "TEST-2"]
    assert [item["code"] for item in payload["issues"]] == [
        "UNKNOWN_RID",
        "MODULE_NOT_FOUND",
    ]
