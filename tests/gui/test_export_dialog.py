"""GUI tests for the requirement export dialog."""

from __future__ import annotations

import pytest


pytestmark = pytest.mark.gui


@pytest.mark.gui_smoke
def test_export_dialog_text_options_visibility(wx_app):
    _wx = pytest.importorskip("wx")
    from app.ui.export_dialog import RequirementExportDialog

    dialog = RequirementExportDialog(
        None,
        available_fields=["id", "statement"],
        selected_fields=["statement"],
        document_label="DOC",
    )
    try:
        wx_app.Yield()
        assert dialog.txt_options_box.IsShown()
        assert dialog.columns_box.IsShown()
        assert not dialog.docx_formula_box.IsShown()

        dialog.format_choice.SetSelection(1)
        dialog._update_text_options_visibility()
        dialog._update_columns_visibility()
        dialog._update_docx_options_visibility()
        wx_app.Yield()
        assert dialog.txt_options_box.IsShown()
        assert dialog.columns_box.IsShown()
        assert not dialog.docx_formula_box.IsShown()

        dialog.format_choice.SetSelection(2)
        dialog._update_text_options_visibility()
        dialog._update_columns_visibility()
        dialog._update_docx_options_visibility()
        wx_app.Yield()
        assert dialog.txt_options_box.IsShown()
        assert dialog.columns_box.IsShown()
        assert dialog.docx_formula_box.IsShown()

        dialog.format_choice.SetSelection(0)
        dialog._update_text_options_visibility()
        dialog._update_columns_visibility()
        dialog._update_docx_options_visibility()
        wx_app.Yield()
        assert dialog.txt_options_box.IsShown()
        assert dialog.columns_box.IsShown()
        assert not dialog.docx_formula_box.IsShown()
    finally:
        dialog.Destroy()
        wx_app.Yield()


@pytest.mark.gui_smoke
def test_export_dialog_card_sort_defaults_and_plan(wx_app):
    _wx = pytest.importorskip("wx")
    from app.config import ExportDialogState
    from app.ui.export_dialog import RequirementExportDialog

    dialog = RequirementExportDialog(
        None,
        available_fields=["id", "statement", "labels", "source"],
        selected_fields=["statement"],
        saved_state=ExportDialogState(
            path="/tmp/export.txt",
            format="txt",
            columns=["title", "statement"],
            order=["title", "statement", "id"],
            empty_fields_placeholder=False,
            docx_formula_renderer=None,
            card_sort_mode="source",
        ),
    )
    try:
        wx_app.Yield()
        assert dialog._selected_card_sort_mode() == "source"

        dialog.card_sort_choice.SetSelection(1)
        assert dialog._selected_card_sort_mode() == "labels"

        plan = dialog.get_plan()
        assert plan is not None
        assert plan.card_sort_mode == "labels"

        state = dialog.get_state()
        assert state.card_sort_mode == "labels"
    finally:
        dialog.Destroy()
        wx_app.Yield()
