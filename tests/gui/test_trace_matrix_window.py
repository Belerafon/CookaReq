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
    TraceDirectionalTablesFrame,
    TraceMatrixDisplayOptions,
    TraceMatrixConfigDialog,
    TraceMatrixFrame,
    _write_combined_html,
    _write_combined_markdown,
    _write_combined_pdf,
    _write_directional_html,
    _write_directional_markdown,
    _write_directional_pdf,
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
        first._view_mode.SetSelection(2)  # matrix + directional tables
        for idx in range(first._row_fields.GetCount()):
            first._row_fields.Check(idx, False)
            first._column_fields.Check(idx, False)
        first._row_fields.Check(0, True)  # rid
        first._row_fields.Check(2, True)  # status
        first._column_fields.Check(0, True)  # rid
        first._column_fields.Check(1, True)  # title
        _ = first.get_plan()
    finally:
        first.Close()
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
        assert second._view_mode.GetSelection() == 2

        plan = second.get_plan()
        assert plan.config.direction == TraceDirection.PARENT_TO_CHILD
        assert plan.options.row_fields == ("rid", "status")
        assert plan.options.column_fields == ("rid", "title")
        assert plan.options.view_mode == "combined"
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


def test_trace_directional_tables_frame_renders_both_tabs(wx_app, tmp_path):
    _wx = pytest.importorskip("wx")
    controller = DocumentsController(RequirementsService(tmp_path), RequirementModel())

    top = Document(prefix="TOP", title="Top")
    top_dir = tmp_path / "TOP"
    save_document(top_dir, top)
    save_item(top_dir, top, _requirement(1, "Top requirement", doc_prefix="TOP").to_mapping())

    low = Document(prefix="LOW", title="Low", parent="TOP")
    low_dir = tmp_path / "LOW"
    save_document(low_dir, low)
    save_item(low_dir, low, _requirement(1, "Low linked", doc_prefix="LOW", links=[Link(rid="TOP1")]).to_mapping())
    save_item(low_dir, low, _requirement(2, "Low orphan", doc_prefix="LOW").to_mapping())

    controller.load_documents()
    views = controller.build_trace_views(
        TraceMatrixConfig(
            rows=TraceMatrixAxisConfig(documents=("LOW",)),
            columns=TraceMatrixAxisConfig(documents=("TOP",)),
        )
    )
    frame = TraceDirectionalTablesFrame(None, views)
    try:
        frame.Show()
        wx_app.Yield()
        notebook = next((child for child in frame.GetChildren() if isinstance(child, _wx.Notebook)), None)
        assert isinstance(notebook, _wx.Notebook)
        assert notebook.GetPageCount() == 2
        assert notebook.GetPageText(0) == "Top → Bottom"
        assert notebook.GetPageText(1) == "Bottom → Top"

        first_panel = notebook.GetPage(0)
        assert hasattr(first_panel, "_column_filter_ctrls")
        rid_filter = first_panel._column_filter_ctrls["rid"]
        rid_filter.SetValue("LOW1")
        wx_app.Yield()
        assert "1/2" in first_panel._summary.GetLabel()

        rid_filter.SetValue("=LOW2")
        wx_app.Yield()
        assert "1/2" in first_panel._summary.GetLabel()

        rid_filter.SetValue("~LOW[12]")
        wx_app.Yield()
        assert "2/2" in first_panel._summary.GetLabel()

        target_filter = first_panel._column_filter_ctrls["__targets__"]
        target_filter.SetValue("empty")
        wx_app.Yield()
        assert "1/2" in first_panel._summary.GetLabel()

        first_panel._on_clear_column_filters(_wx.CommandEvent())
        wx_app.Yield()
        assert "2/2" in first_panel._summary.GetLabel()
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_trace_directional_and_combined_exports(wx_app, tmp_path):
    pytest.importorskip("wx")
    controller = DocumentsController(RequirementsService(tmp_path), RequirementModel())

    top = Document(prefix="TOP", title="Top")
    top_dir = tmp_path / "TOP"
    save_document(top_dir, top)
    save_item(top_dir, top, _requirement(1, "Top requirement", doc_prefix="TOP").to_mapping())

    low = Document(prefix="LOW", title="Low", parent="TOP")
    low_dir = tmp_path / "LOW"
    save_document(low_dir, low)
    save_item(low_dir, low, _requirement(1, "Low linked", doc_prefix="LOW", links=[Link(rid="TOP1")]).to_mapping())
    save_item(low_dir, low, _requirement(2, "Low orphan", doc_prefix="LOW").to_mapping())

    controller.load_documents()
    config = TraceMatrixConfig(
        rows=TraceMatrixAxisConfig(documents=("LOW",)),
        columns=TraceMatrixAxisConfig(documents=("TOP",)),
    )
    matrix = controller.build_trace_matrix(config)
    views = controller.build_trace_views(config)
    options = TraceMatrixDisplayOptions(row_fields=("rid", "title"), column_fields=("rid", "title"))

    directional_md = tmp_path / "directional.md"
    _write_directional_markdown(directional_md, views, options)
    markdown_text = directional_md.read_text(encoding="utf-8")
    assert "Top → Bottom" in markdown_text
    assert "—" in markdown_text

    directional_html = tmp_path / "directional.html"
    _write_directional_html(directional_html, views, options)
    html_text = directional_html.read_text(encoding="utf-8")
    assert "Trace directional tables" in html_text
    assert "Top → Bottom" in html_text

    directional_pdf = tmp_path / "directional.pdf"
    _write_directional_pdf(directional_pdf, views, options)
    assert directional_pdf.exists()
    assert directional_pdf.stat().st_size > 0

    combined_md = tmp_path / "combined.md"
    _write_combined_markdown(combined_md, matrix, views, options)
    combined_md_text = combined_md.read_text(encoding="utf-8")
    assert "Trace report" in combined_md_text
    assert "## Matrix" in combined_md_text
    assert "## Directional views" in combined_md_text

    combined_html = tmp_path / "combined.html"
    _write_combined_html(combined_html, matrix, views, options)
    combined_html_text = combined_html.read_text(encoding="utf-8")
    assert "Trace report" in combined_html_text
    assert "Directional views" in combined_html_text

    combined_pdf = tmp_path / "combined.pdf"
    _write_combined_pdf(combined_pdf, matrix, views, options)
    assert combined_pdf.exists()
    assert combined_pdf.stat().st_size > 0


def test_trace_directional_tables_frame_persists_preferences(wx_app, tmp_path):
    wx = pytest.importorskip("wx")
    controller = DocumentsController(RequirementsService(tmp_path), RequirementModel())

    top = Document(prefix="TOP", title="Top")
    top_dir = tmp_path / "TOP"
    save_document(top_dir, top)
    save_item(top_dir, top, _requirement(1, "Top requirement", doc_prefix="TOP").to_mapping())

    low = Document(prefix="LOW", title="Low", parent="TOP")
    low_dir = tmp_path / "LOW"
    save_document(low_dir, low)
    save_item(low_dir, low, _requirement(1, "Low linked", doc_prefix="LOW", links=[Link(rid="TOP1")]).to_mapping())
    save_item(low_dir, low, _requirement(2, "Low orphan", doc_prefix="LOW").to_mapping())

    controller.load_documents()
    views = controller.build_trace_views(
        TraceMatrixConfig(
            rows=TraceMatrixAxisConfig(documents=("LOW",)),
            columns=TraceMatrixAxisConfig(documents=("TOP",)),
        )
    )

    first = TraceDirectionalTablesFrame(None, views)
    try:
        first.Show()
        wx_app.Yield()
        first.SetSize((first.FromDIP(1240), first.FromDIP(740)))
        first._forward_panel._filter_ctrl.SetValue("low")
        first._forward_panel._column_filter_ctrls["rid"].SetValue("=LOW1")
        event = wx.ListEvent()
        event.SetColumn(1)
        first._forward_panel._on_column_clicked(event)
        wx_app.Yield()
    finally:
        first.Close()
        wx_app.Yield()

    second = TraceDirectionalTablesFrame(None, views)
    try:
        width, height = second.GetSize()
        assert width >= second.FromDIP(1200)
        assert height >= second.FromDIP(700)
        assert second._forward_panel._filter_ctrl.GetValue() == "low"
        assert second._forward_panel._column_filter_ctrls["rid"].GetValue() == "=LOW1"
        assert second._forward_panel._sort_column == 1
    finally:
        second.Destroy()
        wx_app.Yield()
