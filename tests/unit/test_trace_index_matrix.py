from collections import Counter
from pathlib import Path

import pytest

from app.core.trace_index import (
    CodeLocation,
    TestCaseRef,
    TestResultRef,
    TraceArtifactMatrix,
    TraceIndex,
    TraceIndexConfig,
    TraceRequirementRef,
    build_artifact_trace_matrix,
    build_trace_index,
)

FIXTURE_ROOT = Path("tests/fixtures/trace_index_project")


@pytest.mark.unit
def test_build_artifact_trace_matrix_from_fixture() -> None:
    config = TraceIndexConfig.from_conventions(
        FIXTURE_ROOT / "Req",
        project_root=FIXTURE_ROOT,
        exclude_globs=("Vsrc/broken_*",),
    )

    index = build_trace_index(config)
    matrix = build_artifact_trace_matrix(index)

    assert isinstance(matrix, TraceArtifactMatrix)
    assert len(matrix.requirements) == 12
    assert len(matrix.columns) == 30
    assert len(matrix.cells) == 44
    assert Counter(column.kind for column in matrix.columns) == {
        "code": 20,
        "test_case": 5,
        "test_result": 5,
    }
    assert Counter(cell.marker for cell in matrix.cells) == {
        "code": 20,
        "test_case": 12,
        "test_result": 12,
    }

    llr10_cells = matrix.cells_for("LLR10")

    assert {cell.marker for cell in llr10_cells} == {
        "code",
        "test_case",
        "test_result",
    }
    assert any(cell.status == "passed" for cell in llr10_cells)
    assert all(cell.rid == "LLR10" for cell in llr10_cells)

    payload = matrix.to_dict()

    assert payload["requirements"][0]["rid"] == "LLR1"
    assert payload["columns"][0]["kind"] == "code"
    assert payload["cells"][0]["rid"]


@pytest.mark.unit
def test_build_artifact_trace_matrix_skips_unknown_rids() -> None:
    index = TraceIndex(
        project_root=".",
        req_root="Req",
        config_hash="config",
        input_fingerprint="fingerprint",
        requirements=(TraceRequirementRef(rid="LLR1"),),
        code_locations=(
            CodeLocation(
                rid="LLR99",
                path="src/demo.c",
                line_start=1,
                line_end=1,
                marker_text="@covers LLR99",
                marker_ordinal=1,
            ),
        ),
        test_cases=(
            TestCaseRef(
                test_id="TEST-1",
                path="tests/test_demo.c",
                line_start=1,
                line_end=1,
                covers=("LLR1", "LLR99"),
            ),
        ),
        test_results=(
            TestResultRef(
                run_id="RUN-1",
                test_id="TEST-1",
                result_file="tests/results.txt",
                block_ordinal=1,
                raw_status="FAILED",
                normalized_status="failed",
                covers=("LLR1", "LLR99"),
            ),
        ),
    )

    matrix = build_artifact_trace_matrix(index)

    assert {cell.rid for cell in matrix.cells} == {"LLR1"}
    assert any(
        cell.marker == "test_result" and cell.status == "failed"
        for cell in matrix.cells
    )
