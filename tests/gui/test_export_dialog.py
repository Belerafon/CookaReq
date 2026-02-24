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
        assert dialog.docx_include_requirement_heading_checkbox.GetValue() is True

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
        assert plan.docx_include_requirement_heading is True

        state = dialog.get_state()
        assert state.export_scope == "all"
        assert state.colorize_label_backgrounds is True
        assert state.docx_include_requirement_heading is True
    finally:
        dialog.Destroy()
        wx_app.Yield()


@pytest.mark.gui_smoke
def test_export_dialog_docx_formula_default_is_auto(wx_app):
    from app.ui.export_dialog import ExportFormat, RequirementExportDialog

    dialog = RequirementExportDialog(
        None,
        available_fields=["id", "statement"],
        selected_fields=["statement"],
    )
    try:
        wx_app.Yield()
        dialog.format_choice.SetSelection(2)
        dialog._on_format_changed(pytest.importorskip("wx").CommandEvent())
        assert dialog.docx_formula_choice.GetSelection() == 0

        dialog._on_clear(pytest.importorskip("wx").CommandEvent())
        assert dialog.get_plan() is None

        dialog.docx_include_requirement_heading_checkbox.SetValue(True)
        dialog._on_docx_heading_toggle(pytest.importorskip("wx").CommandEvent())
        dialog.file_picker.SetPath("/tmp/export.docx")
        plan_with_compact_mode = dialog.get_plan()
        assert plan_with_compact_mode is not None
        assert plan_with_compact_mode.columns == []

        dialog.docx_include_requirement_heading_checkbox.SetValue(False)
        dialog._on_docx_heading_toggle(pytest.importorskip("wx").CommandEvent())
        plan = dialog.get_plan()
        assert plan is None

        dialog._on_select_all(pytest.importorskip("wx").CommandEvent())
        plan = dialog.get_plan()
        assert plan is not None
        assert plan.format == ExportFormat.DOCX
        assert plan.docx_formula_renderer == "auto"
        assert plan.docx_include_requirement_heading is False

        state = dialog.get_state()
        assert state.docx_formula_renderer == "auto"
        assert state.docx_include_requirement_heading is False
    finally:
        dialog.Destroy()
        wx_app.Yield()


@pytest.mark.gui_smoke
def test_export_dialog_default_columns_match_export_preset(wx_app):
    from app.ui.export_dialog import RequirementExportDialog

    dialog = RequirementExportDialog(
        None,
        available_fields=[
            "labels",
            "id",
            "source",
            "status",
            "statement",
            "type",
            "owner",
            "priority",
            "verification",
            "acceptance",
            "conditions",
            "rationale",
            "assumptions",
            "modified_at",
            "attachments",
            "revision",
            "approved_at",
            "notes",
            "links",
            "doc_prefix",
            "rid",
            "derived_from",
            "derived_count",
        ],
        selected_fields=["status"],
    )
    try:
        wx_app.Yield()
        assert dialog._field_order == [
            "title",
            "labels",
            "id",
            "source",
            "status",
            "statement",
            "type",
            "owner",
            "priority",
            "verification",
            "acceptance",
            "conditions",
            "rationale",
            "assumptions",
            "modified_at",
            "attachments",
            "revision",
            "approved_at",
            "notes",
            "links",
            "doc_prefix",
            "rid",
            "derived_from",
            "derived_count",
        ]
        assert dialog._checked_fields() == [
            "title",
            "labels",
            "id",
            "source",
            "statement",
            "owner",
            "verification",
            "acceptance",
            "conditions",
            "rationale",
            "assumptions",
            "modified_at",
            "attachments",
            "revision",
            "approved_at",
            "notes",
            "links",
            "doc_prefix",
            "rid",
            "derived_from",
            "derived_count",
        ]
    finally:
        dialog.Destroy()
        wx_app.Yield()
