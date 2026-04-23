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
)
from app.core.trace_matrix import TraceDirection, TraceMatrixAxisConfig, TraceMatrixConfig
from app.services.requirements import RequirementsService
from app.ui.controllers import DocumentsController
from app.ui.requirement_model import RequirementModel
from app.ui.trace_matrix import (
    TraceMatrixConfigDialog,
    TraceMatrixFrame,
    _build_health_snapshot,
    _format_health_report,
)

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

    controller = DocumentsController(RequirementsService(tmp_path), RequirementModel())

    hlr = Document(prefix="HLR", title="High Level")
    hlr_dir = tmp_path / "HLR"
    save_document(hlr_dir, hlr)
    hlr_req = _requirement(1, "HLR Requirement", doc_prefix="HLR")
    save_item(hlr_dir, hlr, hlr_req.to_mapping())

    sys = Document(prefix="SYS", title="System", parent="HLR")
    sys_dir = tmp_path / "SYS"
    save_document(sys_dir, sys)

    link = Link(rid="HLR1")
    sys_req_linked = _requirement(1, "SYS covers HLR", doc_prefix="SYS", links=[link])
    save_item(sys_dir, sys, sys_req_linked.to_mapping())

    sys_req_orphan = _requirement(2, "SYS orphan", doc_prefix="SYS")
    save_item(sys_dir, sys, sys_req_orphan.to_mapping())

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
        assert frame.grid.GetCellValue(1, 0) in {"", "·"}

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

        health = frame.health_panel._overview.GetLabel()
        assert "Coverage:" in health
        assert "Suspect links:" in health

        orphan_rows = frame.health_panel._orphan_rows.GetLabel()
        assert "SYS2" in orphan_rows

        orphan_columns = frame.health_panel._orphan_columns.GetLabel()
        assert "none" in orphan_columns

        report = _format_health_report(_build_health_snapshot(frame.matrix))
        assert "Trace Matrix Health" in report
        assert "Orphan rows:" in report
        assert "SYS2" in report
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_trace_matrix_dialog_persists_preferences(wx_app):
    """Dialog should restore previously used matrix preferences."""

    _wx = pytest.importorskip("wx")
    docs = {
        "HLR": Document(prefix="HLR", title="High"),
        "SYS": Document(prefix="SYS", title="System", parent="HLR"),
    }

    first = TraceMatrixConfigDialog(None, docs, default_rows="SYS", default_columns="HLR")
    try:
        first._rows_choice.SetSelection(1)  # SYS
        first._columns_choice.SetSelection(0)  # HLR
        first._rows_sort.SetSelection(1)  # title
        first._columns_sort.SetSelection(2)  # status
        first._direction_choice.SetSelection(1)  # parent-to-child
        first._compact_symbols.SetValue(False)
        first._hide_unlinked.SetValue(True)
        first._output_format.SetSelection(2)  # matrix-csv
        for idx in range(first._fields.GetCount()):
            first._fields.Check(idx, False)
        first._fields.Check(0, True)  # rid
        first._fields.Check(2, True)  # status
        _ = first.get_plan()
    finally:
        first.Destroy()
        wx_app.Yield()

    second = TraceMatrixConfigDialog(None, docs, default_rows="HLR", default_columns="SYS")
    try:
        assert second._rows_choice.GetStringSelection().startswith("SYS")
        assert second._columns_choice.GetStringSelection().startswith("HLR")
        assert second._rows_sort.GetSelection() == 1
        assert second._columns_sort.GetSelection() == 2
        assert second._direction_choice.GetSelection() == 1
        assert second._compact_symbols.GetValue() is False
        assert second._hide_unlinked.GetValue() is True
        assert second._output_format.GetString(second._output_format.GetSelection()) == "matrix-csv"

        plan = second.get_plan()
        assert plan.config.direction == TraceDirection.PARENT_TO_CHILD
        assert plan.options.selected_fields == ("rid", "status")
    finally:
        second.Destroy()
        wx_app.Yield()


def test_trace_matrix_frame_persists_window_size(wx_app, tmp_path):
    """Matrix frame should restore last persisted size."""

    _wx = pytest.importorskip("wx")
    controller = DocumentsController(RequirementsService(tmp_path), RequirementModel())

    hlr = Document(prefix="HLR", title="High Level")
    hlr_dir = tmp_path / "HLR"
    save_document(hlr_dir, hlr)
    save_item(hlr_dir, hlr, _requirement(1, "HLR Requirement", doc_prefix="HLR").to_mapping())

    sys = Document(prefix="SYS", title="System", parent="HLR")
    sys_dir = tmp_path / "SYS"
    save_document(sys_dir, sys)
    save_item(sys_dir, sys, _requirement(1, "SYS", doc_prefix="SYS", links=[Link(rid="HLR1")]).to_mapping())

    controller.load_documents()
    config = TraceMatrixConfig(
        rows=TraceMatrixAxisConfig(documents=("SYS",)),
        columns=TraceMatrixAxisConfig(documents=("HLR",)),
    )
    matrix = controller.build_trace_matrix(config)

    first = TraceMatrixFrame(None, controller, config, matrix)
    try:
        first.SetSize((first.FromDIP(1280), first.FromDIP(760)))
    finally:
        first.Destroy()
        wx_app.Yield()

    second = TraceMatrixFrame(None, controller, config, matrix)
    try:
        width, height = second.GetSize()
        assert width >= second.FromDIP(1200)
        assert height >= second.FromDIP(720)
    finally:
        second.Destroy()
        wx_app.Yield()
