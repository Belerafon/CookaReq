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
        assert not dialog.colorize_label_backgrounds_checkbox.IsEnabled()
        assert dialog._selected_export_scope() == "all"

        dialog.format_choice.SetSelection(1)
        dialog._update_text_options_visibility()
        dialog._update_columns_visibility()
        dialog._update_docx_options_visibility()
        wx_app.Yield()
        assert dialog.txt_options_box.IsShown()
        assert dialog.columns_box.IsShown()
        assert not dialog.docx_formula_box.IsShown()
        assert dialog.colorize_label_backgrounds_checkbox.IsEnabled()
        assert dialog._selected_export_scope() == "all"

        dialog.format_choice.SetSelection(2)
        dialog._update_text_options_visibility()
        dialog._update_columns_visibility()
        dialog._update_docx_options_visibility()
        wx_app.Yield()
        assert dialog.txt_options_box.IsShown()
        assert dialog.columns_box.IsShown()
        assert dialog.docx_formula_box.IsShown()
        assert dialog.colorize_label_backgrounds_checkbox.IsEnabled()

        dialog.format_choice.SetSelection(0)
        dialog._update_text_options_visibility()
        dialog._update_columns_visibility()
        dialog._update_docx_options_visibility()
        wx_app.Yield()
        assert dialog.txt_options_box.IsShown()
        assert dialog.columns_box.IsShown()
        assert not dialog.docx_formula_box.IsShown()
        assert not dialog.colorize_label_backgrounds_checkbox.IsEnabled()
        assert dialog._selected_export_scope() == "all"
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
            card_label_group_mode="per_label",
            export_scope="visible",
        ),
    )
    try:
        wx_app.Yield()
        assert dialog._selected_card_sort_mode() == "source"
        assert dialog._selected_export_scope() == "visible"
        assert dialog._selected_card_label_group_mode() == "per_label"
        assert not dialog.card_label_group_choice.IsEnabled()

        dialog.card_sort_choice.SetSelection(1)
        dialog._on_card_sort_changed(_wx.CommandEvent())
        assert dialog._selected_card_sort_mode() == "labels"
        assert dialog.card_label_group_choice.IsEnabled()
        dialog.card_label_group_choice.SetSelection(1)
        assert dialog._selected_card_label_group_mode() == "label_set"

        plan = dialog.get_plan()
        assert plan is not None
        assert plan.card_sort_mode == "labels"
        assert plan.card_label_group_mode == "label_set"

        state = dialog.get_state()
        assert state.card_sort_mode == "labels"
        assert state.card_label_group_mode == "label_set"
    finally:
        dialog.Destroy()
        wx_app.Yield()


@pytest.mark.gui_smoke
def test_export_dialog_default_scope_from_context(wx_app):
    _wx = pytest.importorskip("wx")
    from app.ui.export_dialog import RequirementExportDialog

    dialog = RequirementExportDialog(
        None,
        available_fields=["id", "statement"],
        selected_fields=["statement"],
        default_export_scope="selected",
    )
    try:
        wx_app.Yield()
        assert dialog._selected_export_scope() == "selected"

        dialog.scope_choice.SetSelection(0)
        dialog._on_scope_changed(_wx.CommandEvent())

        plan = dialog.get_plan()
        assert plan is None

        dialog.file_picker.SetPath("/tmp/export.txt")
        dialog.colorize_label_backgrounds_checkbox.SetValue(True)
        plan = dialog.get_plan()
        assert plan is not None
        assert plan.export_scope == "all"
        assert plan.colorize_label_backgrounds is True

        state = dialog.get_state()
        assert state.export_scope == "all"
        assert state.colorize_label_backgrounds is True
    finally:
        dialog.Destroy()
        wx_app.Yield()
