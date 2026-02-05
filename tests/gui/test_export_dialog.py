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
