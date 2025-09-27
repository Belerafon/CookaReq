"""GUI tests for the traceability matrix window."""

from __future__ import annotations

import pytest

from app.core.document_store import Document, save_document, save_item
from app.core.model import (
    Link,
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
    requirement_to_dict,
)
from app.core.trace_matrix import TraceMatrixAxisConfig, TraceMatrixConfig
from app.ui.controllers import DocumentsController
from app.ui.requirement_model import RequirementModel
from app.ui.trace_matrix import TraceMatrixFrame

pytestmark = pytest.mark.gui


def _requirement(
    req_id: int,
    title: str,
    *,
    doc_prefix: str,
    links: list[Link] | None = None,
) -> Requirement:
    req = Requirement(
        id=req_id,
        title=title,
        statement="",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="",
        priority=Priority.MEDIUM,
        source="",
        verification=Verification.ANALYSIS,
        links=list(links or []),
    )
    req.doc_prefix = doc_prefix
    req.rid = f"{doc_prefix}{req_id}"
    return req


def test_trace_matrix_frame_renders_links(wx_app, tmp_path):
    """The matrix grid should highlight linked pairs and show details."""

    _wx = pytest.importorskip("wx")

    controller = DocumentsController(tmp_path, RequirementModel())

    hlr = Document(prefix="HLR", title="High Level")
    hlr_dir = tmp_path / "HLR"
    save_document(hlr_dir, hlr)
    hlr_req = _requirement(1, "HLR Requirement", doc_prefix="HLR")
    save_item(hlr_dir, hlr, requirement_to_dict(hlr_req))

    sys = Document(prefix="SYS", title="System", parent="HLR")
    sys_dir = tmp_path / "SYS"
    save_document(sys_dir, sys)

    link = Link(rid="HLR1")
    sys_req_linked = _requirement(1, "SYS covers HLR", doc_prefix="SYS", links=[link])
    save_item(sys_dir, sys, requirement_to_dict(sys_req_linked))

    sys_req_orphan = _requirement(2, "SYS orphan", doc_prefix="SYS")
    save_item(sys_dir, sys, requirement_to_dict(sys_req_orphan))

    controller.load_documents()

    config = TraceMatrixConfig(
        rows=TraceMatrixAxisConfig(documents=("SYS",)),
        columns=TraceMatrixAxisConfig(documents=("HLR",)),
    )
    matrix = controller.build_trace_matrix(config)

    frame = TraceMatrixFrame(None, controller, config, matrix)
    try:
        frame.Show()
        wx_app.Yield()

        assert frame.grid.GetNumberRows() == len(matrix.rows)
        assert frame.grid.GetNumberCols() == len(matrix.columns)
        assert frame.grid.GetRowLabelSize() >= frame.FromDIP(220)
        assert frame.grid.GetRowSize(0) >= frame.FromDIP(56)
        assert frame.grid.GetColSize(0) >= frame.FromDIP(90)
        assert frame.grid.GetColLabelSize() >= frame.FromDIP(72)
        assert frame.grid.GetCellValue(0, 0) != ""
        assert frame.grid.GetCellValue(1, 0) == ""

        row_label = frame.grid.GetRowLabelValue(0)
        assert "SYS1" in row_label
        col_label = frame.grid.GetColLabelValue(0)
        assert "HLR1" in col_label

        frame._show_cell_details(0, 0)
        wx_app.Yield()
        assert "HLR1" in frame.details_panel._links_text.GetLabel()

        frame._show_row_details(1)
        wx_app.Yield()
        assert "SYS2" in frame.details_panel._row_text.GetLabel()

        summary = frame._summary.GetLabel()
        assert "2 × 1" in summary
    finally:
        frame.Destroy()
        wx_app.Yield()
