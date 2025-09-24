import pytest

from app.core.document_store import Document, save_document, save_item
from app.core.trace_matrix import (
    TraceDirection,
    TraceMatrixAxisConfig,
    TraceMatrixConfig,
    build_trace_matrix,
)


def _write_documents(root):
    doc_sys = Document(prefix="SYS", title="System")
    doc_hlr = Document(prefix="HLR", title="High", parent="SYS")
    doc_sw = Document(prefix="SW", title="Software", parent="HLR")
    save_document(root / "SYS", doc_sys)
    save_document(root / "HLR", doc_hlr)
    save_document(root / "SW", doc_sw)
    save_item(
        root / "SYS",
        doc_sys,
        {
            "id": 1,
            "title": "System requirement",
            "statement": "Initial",
            "labels": [],
            "links": [],
            "status": "approved",
        },
    )
    save_item(
        root / "HLR",
        doc_hlr,
        {
            "id": 1,
            "title": "High level",
            "statement": "Derived",
            "labels": ["safety"],
            "links": ["SYS1"],
            "status": "approved",
        },
    )
    save_item(
        root / "HLR",
        doc_hlr,
        {
            "id": 2,
            "title": "High level extra",
            "statement": "No link",
            "labels": ["performance"],
            "links": [],
            "status": "draft",
        },
    )
    save_item(
        root / "SW",
        doc_sw,
        {
            "id": 1,
            "title": "Software requirement",
            "statement": "Trace to HLR1",
            "labels": [],
            "links": ["HLR1"],
            "status": "approved",
        },
    )
    return doc_sys


@pytest.mark.unit
def test_build_trace_matrix_child_to_parent(tmp_path):
    _write_documents(tmp_path)
    config = TraceMatrixConfig(
        rows=TraceMatrixAxisConfig(documents=("HLR",)),
        columns=TraceMatrixAxisConfig(documents=("SYS",)),
    )
    matrix = build_trace_matrix(tmp_path, config)

    assert [entry.rid for entry in matrix.rows] == ["HLR1", "HLR2"]
    assert [entry.rid for entry in matrix.columns] == ["SYS1"]
    assert ("HLR1", "SYS1") in matrix.cells
    assert matrix.cells[("HLR1", "SYS1")].suspect is False
    assert matrix.summary.total_rows == 2
    assert matrix.summary.total_columns == 1
    assert matrix.summary.linked_pairs == 1
    assert matrix.summary.row_coverage == pytest.approx(0.5)
    assert matrix.summary.column_coverage == pytest.approx(1.0)
    assert matrix.summary.orphan_rows == ("HLR2",)


@pytest.mark.unit
def test_build_trace_matrix_parent_to_child(tmp_path):
    _write_documents(tmp_path)
    config = TraceMatrixConfig(
        rows=TraceMatrixAxisConfig(documents=("SYS",)),
        columns=TraceMatrixAxisConfig(documents=("HLR",)),
        direction=TraceDirection.PARENT_TO_CHILD,
    )
    matrix = build_trace_matrix(tmp_path, config)

    assert [entry.rid for entry in matrix.rows] == ["SYS1"]
    assert [entry.rid for entry in matrix.columns] == ["HLR1", "HLR2"]
    assert ("SYS1", "HLR1") in matrix.cells
    assert matrix.summary.link_count == 1
    assert matrix.summary.linked_pairs == 1
    assert matrix.summary.orphan_columns == ("HLR2",)


@pytest.mark.unit
def test_axis_filters_apply(tmp_path):
    _write_documents(tmp_path)
    config = TraceMatrixConfig(
        rows=TraceMatrixAxisConfig(
            documents=("HLR",),
            labels_all=("safety",),
            statuses=("approved",),
        ),
        columns=TraceMatrixAxisConfig(documents=("SYS",)),
    )
    matrix = build_trace_matrix(tmp_path, config)
    assert [entry.rid for entry in matrix.rows] == ["HLR1"]
    assert matrix.summary.total_rows == 1


@pytest.mark.unit
def test_suspect_links_detected(tmp_path):
    doc_sys = _write_documents(tmp_path)
    # Update parent requirement to invalidate stored fingerprint in HLR1 link
    save_item(
        tmp_path / "SYS",
        doc_sys,
        {
            "id": 1,
            "title": "System requirement",
            "statement": "Modified",
            "labels": [],
            "links": [],
            "status": "approved",
        },
    )
    config = TraceMatrixConfig(
        rows=TraceMatrixAxisConfig(documents=("HLR",), labels_all=("safety",)),
        columns=TraceMatrixAxisConfig(documents=("SYS",)),
    )
    matrix = build_trace_matrix(tmp_path, config)
    cell = matrix.cells[("HLR1", "SYS1")]
    assert cell.suspect is True
    assert cell.links[0].suspect is True
