"""GUI tests for the requirement import dialog."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


pytestmark = [pytest.mark.gui, pytest.mark.gui_smoke]


def _select_path(dialog, path):
    """Simulate a file picker event for ``path``."""

    dialog._on_file_selected(SimpleNamespace(GetPath=lambda: str(path)))


def test_import_dialog_csv_autopreview_enables_ok(wx_app, tmp_path):
    _wx = pytest.importorskip("wx")
    from app.ui.import_dialog import RequirementImportDialog

    csv_path = tmp_path / "requirements.csv"
    csv_path.write_text(
        "statement,labels\nImplement feature,alpha;beta\nReview design,\n",
        encoding="utf-8",
    )

    dialog = RequirementImportDialog(None, existing_ids=[1, 2], next_id=3, document_label="DOC")
    try:
        _select_path(dialog, csv_path)
        wx_app.Yield()

        mapping = dialog._collect_mapping()
        assert mapping["statement"] == 0
        assert dialog.ok_button.IsEnabled()

        summary = dialog.summary_text.GetLabel()
        assert "import 2 requirement(s)" in summary
        assert not dialog.error_text.IsShown()

        plan = dialog.get_plan()
        assert plan is not None
        assert plan.delimiter == ","
        assert plan.configuration.mapping["statement"] == 0
        assert plan.configuration.mapping.get("labels") == 1

        grid = dialog.preview_grid
        assert grid.GetNumberRows() == 2
        assert grid.GetNumberCols() >= 3
        assert dialog._current_preview is not None
        statements = [req.statement for req in dialog._current_preview.requirements]
        assert statements == ["Implement feature", "Review design"]
    finally:
        dialog.Destroy()
        wx_app.Yield()


def test_import_dialog_requires_statement_mapping(wx_app, tmp_path):
    _wx = pytest.importorskip("wx")
    from app.ui.import_dialog import RequirementImportDialog

    csv_path = tmp_path / "data.csv"
    csv_path.write_text("id,title\n1,Example\n", encoding="utf-8")

    dialog = RequirementImportDialog(None, existing_ids=[], next_id=1)
    try:
        _select_path(dialog, csv_path)
        wx_app.Yield()

        statement_choice = dialog.mapping_controls["statement"]
        statement_choice.SetSelection(0)  # Ignore mapping
        dialog._refresh_preview()
        wx_app.Yield()

        assert not dialog.ok_button.IsEnabled()
        assert "statement field must be mapped" in dialog.summary_text.GetLabel()
        assert dialog.preview_grid.GetNumberRows() == 0
    finally:
        dialog.Destroy()
        wx_app.Yield()


def test_import_dialog_excel_sheet_switch(wx_app, tmp_path):
    wx = pytest.importorskip("wx")
    openpyxl = pytest.importorskip("openpyxl")
    from app.ui.import_dialog import RequirementImportDialog

    workbook = openpyxl.Workbook()
    first = workbook.active
    first.title = "Main"
    first.append(["statement"])
    first.append(["Alpha"])
    second = workbook.create_sheet("Secondary")
    second.append(["statement"])
    second.append(["Beta"])

    xlsx_path = tmp_path / "reqs.xlsx"
    workbook.save(xlsx_path)
    workbook.close()

    dialog = RequirementImportDialog(None, existing_ids=[], next_id=5)
    try:
        _select_path(dialog, xlsx_path)
        wx_app.Yield()

        assert dialog.sheet_choice.IsShown()
        assert dialog.sheet_choice.GetCount() == 2
        assert dialog.preview_grid.GetNumberRows() == 1
        assert dialog._current_preview is not None
        assert [req.statement for req in dialog._current_preview.requirements] == ["Alpha"]

        index = dialog.sheet_choice.FindString("Secondary")
        dialog.sheet_choice.SetSelection(index)
        dialog._on_sheet_changed(wx.CommandEvent())
        wx_app.Yield()

        assert dialog.preview_grid.GetNumberRows() == 1
        assert dialog._current_preview is not None
        assert [req.statement for req in dialog._current_preview.requirements] == ["Beta"]

        plan = dialog.get_plan()
        assert plan is not None
        assert plan.sheet == "Secondary"
    finally:
        dialog.Destroy()
        wx_app.Yield()
