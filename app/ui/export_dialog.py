"""Dialog for exporting requirements into text formats."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal
from pathlib import Path

import wx

from ..config import ExportDialogState
from ..core.requirement_export import export_card_field_order
from ..i18n import _
from . import locale


class ExportFormat(Enum):
    """Supported export formats."""

    TXT = "txt"
    HTML = "html"
    DOCX = "docx"
    CSV = "csv"
    TSV = "tsv"


@dataclass(slots=True)
class RequirementExportPlan:
    """Configuration collected from the export dialog."""

    path: Path
    format: ExportFormat
    columns: list[str]
    empty_fields_placeholder: bool
    docx_formula_renderer: str | None
    card_sort_mode: str
    card_label_group_mode: str
    export_scope: Literal["all", "visible", "selected"]
    colorize_label_backgrounds: bool
    docx_include_requirement_heading: bool


DEFAULT_EXPORT_FIELD_ORDER: tuple[str, ...] = (
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
)

DEFAULT_EXPORT_SELECTED_FIELDS: tuple[str, ...] = (
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
)


class RequirementExportDialog(wx.Dialog):
    """Allow the user to configure export format and columns."""

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        available_fields: list[str],
        selected_fields: list[str],
        document_label: str | None = None,
        default_path: Path | None = None,
        saved_state: ExportDialogState | None = None,
        default_export_scope: Literal["all", "visible", "selected"] = "all",
    ) -> None:
        title = _("Export Requirements")
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._document_label = document_label or ""
        self._available_fields = self._build_available_fields(available_fields)
        selection_seed = list(DEFAULT_EXPORT_SELECTED_FIELDS)
        force_title = False
        if saved_state and saved_state.columns:
            selection_seed = saved_state.columns
        self._default_selected = self._build_default_selected(selection_seed, force_title=force_title)
        self._field_order = self._build_field_order(saved_state.order if saved_state else None)
        self._field_labels = {field: locale.field_label(field) for field in self._available_fields}
        self._saved_format = self._coerce_format(saved_state.format if saved_state else None)
        self._saved_path = Path(saved_state.path) if saved_state and saved_state.path else None
        self._empty_fields_placeholder = (
            bool(saved_state.empty_fields_placeholder) if saved_state else False
        )
        self._docx_formula_renderer = (
            saved_state.docx_formula_renderer if saved_state else None
        )
        self._card_sort_mode = self._coerce_card_sort_mode(
            saved_state.card_sort_mode if saved_state else None
        )
        self._card_label_group_mode = self._coerce_card_label_group_mode(
            saved_state.card_label_group_mode if saved_state else None
        )
        self._colorize_label_backgrounds = (
            bool(saved_state.colorize_label_backgrounds) if saved_state else False
        )
        self._docx_include_requirement_heading = (
            bool(saved_state.docx_include_requirement_heading)
            if saved_state
            else True
        )
        self._default_export_scope: Literal["all", "visible", "selected"] = (
            default_export_scope
            if default_export_scope in {"all", "visible", "selected"}
            else "all"
        )
        self._export_scope = self._coerce_export_scope(
            saved_state.export_scope if saved_state else self._default_export_scope
        )
        self._txt_placeholder_label = _("(not set)")
        self._drag_start_index: int | None = None

        self._create_controls()
        self._bind_events()
        self._arrange_layout()
        if self._saved_format is not None:
            self._apply_format(self._saved_format)
        path = self._saved_path or default_path
        if path:
            path_str = str(path)
            path_str = self._ensure_extension(path_str)
            self.file_picker.SetPath(path_str)
        self._refresh_path_display()
        self._refresh_checklist()
        self._update_text_options_visibility()
        self._update_columns_visibility()
        self._update_docx_options_visibility()
        self._update_ok_state()
        self.SetSize((820, 620))
        self.SetMinSize((420, 520))

    # ------------------------------------------------------------------
    def _build_available_fields(self, available_fields: list[str]) -> list[str]:
        fields = ["title", *available_fields]
        ordered: list[str] = []
        seen: set[str] = set()
        preferred_order = export_card_field_order()
        for field in preferred_order:
            if field in fields and field not in seen:
                seen.add(field)
                ordered.append(field)
        for field in fields:
            if field in seen:
                continue
            seen.add(field)
            ordered.append(field)
        return ordered

    def _build_default_selected(
        self,
        selected_fields: list[str],
        *,
        force_title: bool = True,
    ) -> list[str]:
        base = ["title", *selected_fields] if force_title else list(selected_fields)
        selected: list[str] = []
        seen: set[str] = set()
        for field in base:
            if field not in self._available_fields:
                continue
            if field in seen:
                continue
            seen.add(field)
            selected.append(field)
        if not selected and self._available_fields:
            selected.append(self._available_fields[0])
        return selected

    def _build_field_order(self, initial_order: list[str] | None) -> list[str]:
        ordered: list[str] = []
        if initial_order:
            for field in initial_order:
                if field in self._available_fields and field not in ordered:
                    ordered.append(field)
        if not ordered:
            for field in DEFAULT_EXPORT_FIELD_ORDER:
                if field in self._available_fields and field not in ordered:
                    ordered.append(field)
        for field in self._available_fields:
            if field not in ordered:
                ordered.append(field)
        return ordered

    def _apply_format(self, export_format: ExportFormat) -> None:
        selection_map = {
            ExportFormat.TXT: 0,
            ExportFormat.HTML: 1,
            ExportFormat.DOCX: 2,
            ExportFormat.CSV: 3,
            ExportFormat.TSV: 4,
        }
        self.format_choice.SetSelection(selection_map.get(export_format, 0))

    def _coerce_format(self, value: str | None) -> ExportFormat | None:
        if not value:
            return None
        try:
            return ExportFormat(value)
        except ValueError:
            return None

    def _create_controls(self) -> None:
        self.file_picker = wx.FilePickerCtrl(
            self,
            message=_("Select export file"),
            wildcard=_(
                "Text files (*.txt)|*.txt|HTML files (*.html)|*.html|"
                "DOCX files (*.docx)|*.docx|CSV files (*.csv)|*.csv|"
                "TSV files (*.tsv)|*.tsv|All files|*.*"
            ),
            style=wx.FLP_SAVE | wx.FLP_OVERWRITE_PROMPT,
        )
        self.path_label = wx.StaticText(self, label=_("Export file path"))
        self.path_display = wx.TextCtrl(self, style=wx.TE_READONLY)

        self.format_choice = wx.RadioBox(
            self,
            label=_("Export format"),
            choices=[
                _("Plain text (.txt)"),
                _("HTML (.html)"),
                _("Word (.docx)"),
                _("CSV (.csv)"),
                _("TSV (.tsv)"),
            ],
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )

        self.scope_choice = wx.RadioBox(
            self,
            label=_("Requirements to export"),
            choices=[
                _("All requirements"),
                _("Visible requirements (respect current filter)"),
                _("Selected requirements"),
            ],
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        self._apply_export_scope_choice()

        self.columns_box = wx.StaticBox(self, label=_("Columns"))
        self.column_list = wx.CheckListBox(self.columns_box)

        self.move_up_btn = wx.Button(self.columns_box, label=_("Move Up"))
        self.move_down_btn = wx.Button(self.columns_box, label=_("Move Down"))
        self.select_all_btn = wx.Button(self.columns_box, label=_("Select All"))
        self.clear_btn = wx.Button(self.columns_box, label=_("Clear"))

        self.txt_options_box = wx.StaticBox(self, label=_("Card options"))
        self.txt_empty_fields_checkbox = wx.CheckBox(
            self.txt_options_box,
            label=_("Show empty fields as {placeholder}").format(
                placeholder=self._txt_placeholder_label
            ),
        )
        self.txt_empty_fields_checkbox.SetValue(self._empty_fields_placeholder)
        self.card_sort_label = wx.StaticText(self.txt_options_box, label=_("Card sort order"))
        self.card_sort_choice = wx.Choice(
            self.txt_options_box,
            choices=[
                _("Requirement number"),
                _("Labels"),
                _("Source"),
                _("Title"),
            ],
        )
        self._apply_card_sort_choice()
        self.card_label_group_label = wx.StaticText(
            self.txt_options_box,
            label=_("Label grouping"),
        )
        self.card_label_group_choice = wx.Choice(
            self.txt_options_box,
            choices=[
                _("One group per label (duplicate requirement in every matched label)"),
                _("One group per exact label set"),
            ],
        )
        self._apply_card_label_group_choice()
        self.colorize_label_backgrounds_checkbox = wx.CheckBox(
            self.txt_options_box,
            label=_("Color label backgrounds (HTML/DOCX)"),
        )
        self.colorize_label_backgrounds_checkbox.SetValue(self._colorize_label_backgrounds)

        self.docx_formula_box = wx.StaticBox(self, label=_("DOCX formulas"))
        self.docx_formula_choice = wx.Choice(
            self.docx_formula_box,
            choices=[
                _("Automatic (OMML, then SVG/PNG fallback)"),
                _("MathML (LaTeX → MathML → OMML)"),
                _("SVG (LaTeX → SVG → PNG)"),
                _("PNG (LaTeX → PNG)"),
                _("Plain text"),
            ],
        )
        self.docx_include_requirement_heading_checkbox = wx.CheckBox(
            self.docx_formula_box,
            label=_("Print requirement heading before each card"),
        )
        self.docx_include_requirement_heading_checkbox.SetValue(
            self._docx_include_requirement_heading
        )
        self._apply_docx_formula_choice()

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        ok_button = None
        if hasattr(buttons, "GetAffirmativeButton"):
            try:
                ok_button = buttons.GetAffirmativeButton()
            except TypeError:  # pragma: no cover - older wx versions
                ok_button = None
        if ok_button is None:
            ok_button = self.FindWindowById(wx.ID_OK)
        self.ok_button = ok_button
        self.button_sizer = buttons

    def _bind_events(self) -> None:
        self.file_picker.Bind(wx.EVT_FILEPICKER_CHANGED, self._on_path_changed)
        self.format_choice.Bind(wx.EVT_RADIOBOX, self._on_format_changed)
        self.scope_choice.Bind(wx.EVT_RADIOBOX, self._on_scope_changed)
        self.column_list.Bind(wx.EVT_CHECKLISTBOX, self._on_columns_changed)
        self.card_sort_choice.Bind(wx.EVT_CHOICE, self._on_card_sort_changed)
        self.column_list.Bind(wx.EVT_LEFT_DOWN, self._on_column_left_down)
        self.column_list.Bind(wx.EVT_LEFT_UP, self._on_column_left_up)
        self.move_up_btn.Bind(wx.EVT_BUTTON, lambda _evt: self._move_column(-1))
        self.move_down_btn.Bind(wx.EVT_BUTTON, lambda _evt: self._move_column(1))
        self.select_all_btn.Bind(wx.EVT_BUTTON, self._on_select_all)
        self.clear_btn.Bind(wx.EVT_BUTTON, self._on_clear)
        self.docx_include_requirement_heading_checkbox.Bind(
            wx.EVT_CHECKBOX,
            self._on_docx_heading_toggle,
        )
        self.Bind(wx.EVT_BUTTON, self._on_ok, id=wx.ID_OK)

    def _arrange_layout(self) -> None:
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        if self._document_label:
            doc_text = wx.StaticText(
                self,
                label=_("Target document: {label}").format(label=self._document_label),
            )
            main_sizer.Add(doc_text, 0, wx.BOTTOM, 6)

        main_sizer.Add(self.file_picker, 0, wx.EXPAND | wx.ALL, 10)
        path_sizer = wx.BoxSizer(wx.HORIZONTAL)
        path_sizer.Add(self.path_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        path_sizer.Add(self.path_display, 1, wx.EXPAND)
        main_sizer.Add(path_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        main_sizer.Add(self.format_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)
        main_sizer.Add(self.scope_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        txt_options_sizer = wx.StaticBoxSizer(self.txt_options_box, wx.VERTICAL)
        txt_options_sizer.Add(self.txt_empty_fields_checkbox, 0, wx.ALL, 6)
        sort_row = wx.BoxSizer(wx.HORIZONTAL)
        sort_row.Add(self.card_sort_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        sort_row.Add(self.card_sort_choice, 1, wx.EXPAND)
        txt_options_sizer.Add(sort_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        label_group_row = wx.BoxSizer(wx.HORIZONTAL)
        label_group_row.Add(self.card_label_group_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 8)
        label_group_row.Add(self.card_label_group_choice, 1, wx.EXPAND)
        txt_options_sizer.Add(label_group_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        txt_options_sizer.Add(
            self.colorize_label_backgrounds_checkbox,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            6,
        )
        main_sizer.Add(txt_options_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        docx_options_sizer = wx.StaticBoxSizer(self.docx_formula_box, wx.VERTICAL)
        docx_options_sizer.Add(self.docx_formula_choice, 0, wx.ALL, 6)
        docx_options_sizer.Add(
            self.docx_include_requirement_heading_checkbox,
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            6,
        )
        main_sizer.Add(docx_options_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        columns_sizer = wx.StaticBoxSizer(self.columns_box, wx.VERTICAL)
        list_sizer = wx.BoxSizer(wx.HORIZONTAL)
        list_sizer.Add(self.column_list, 1, wx.EXPAND)

        controls_sizer = wx.BoxSizer(wx.VERTICAL)
        controls_sizer.Add(self.move_up_btn, 0, wx.BOTTOM, 4)
        controls_sizer.Add(self.move_down_btn, 0, wx.BOTTOM, 12)
        controls_sizer.Add(self.select_all_btn, 0, wx.BOTTOM, 4)
        controls_sizer.Add(self.clear_btn, 0)

        list_sizer.Add(controls_sizer, 0, wx.LEFT, 8)
        columns_sizer.Add(list_sizer, 1, wx.EXPAND | wx.ALL, 6)
        main_sizer.Add(columns_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        if self.button_sizer:
            main_sizer.Add(self.button_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        self.SetSizer(main_sizer)
        self.Layout()
        self._main_sizer = main_sizer
        self._txt_options_sizer = txt_options_sizer
        self._columns_sizer = columns_sizer
        self._docx_options_sizer = docx_options_sizer

    # ------------------------------------------------------------------
    def _refresh_checklist(self, *, keep_selection: int | None = None) -> None:
        labels = [self._field_labels[field] for field in self._field_order]
        checked = {self._field_order[i] for i in self.column_list.GetCheckedItems()}
        if not checked:
            checked = set(self._default_selected)
        self.column_list.Set(labels)
        for idx, field in enumerate(self._field_order):
            self.column_list.Check(idx, field in checked)
        if keep_selection is not None and 0 <= keep_selection < len(self._field_order):
            self.column_list.SetSelection(keep_selection)

    def _checked_fields(self) -> list[str]:
        checked_indices = list(self.column_list.GetCheckedItems())
        return [self._field_order[i] for i in checked_indices]

    def _current_format(self) -> ExportFormat:
        selection = self.format_choice.GetSelection()
        if selection == 1:
            return ExportFormat.HTML
        if selection == 2:
            return ExportFormat.DOCX
        if selection == 3:
            return ExportFormat.CSV
        if selection == 4:
            return ExportFormat.TSV
        return ExportFormat.TXT

    def _update_ok_state(self) -> None:
        if not self.ok_button:
            return
        path = self.file_picker.GetPath()
        has_path = bool(path)
        require_columns = not self._can_export_without_columns()
        has_columns = bool(self._checked_fields()) if require_columns else True
        self.ok_button.Enable(has_path and has_columns)

    def _can_export_without_columns(self) -> bool:
        return (
            self._current_format() == ExportFormat.DOCX
            and self.docx_include_requirement_heading_checkbox.GetValue()
        )

    def _update_text_options_visibility(self) -> None:
        show_options = self._current_format() in {
            ExportFormat.TXT,
            ExportFormat.HTML,
            ExportFormat.DOCX,
        }
        self._main_sizer.Show(self._txt_options_sizer, show_options, recursive=True)
        self._update_label_grouping_state()
        self._update_colorize_labels_state()
        self._main_sizer.Layout()

    def _update_columns_visibility(self) -> None:
        self._main_sizer.Show(self._columns_sizer, True, recursive=True)
        self._main_sizer.Layout()

    def _update_docx_options_visibility(self) -> None:
        is_docx = self._current_format() == ExportFormat.DOCX
        self._main_sizer.Show(self._docx_options_sizer, is_docx, recursive=True)
        self._main_sizer.Layout()

    def _coerce_export_scope(self, value: str | None) -> Literal["all", "visible", "selected"]:
        if value in {"all", "visible", "selected"}:
            return value
        return self._default_export_scope

    def _apply_export_scope_choice(self) -> None:
        selection_map = {
            "all": 0,
            "visible": 1,
            "selected": 2,
        }
        self.scope_choice.SetSelection(selection_map.get(self._export_scope, 0))

    def _selected_export_scope(self) -> Literal["all", "visible", "selected"]:
        selection = self.scope_choice.GetSelection()
        if selection == 1:
            return "visible"
        if selection == 2:
            return "selected"
        return "all"

    def _coerce_card_sort_mode(self, value: str | None) -> str:
        if value in {"id", "labels", "source", "title"}:
            return value
        return "id"

    def _apply_card_sort_choice(self) -> None:
        selection_map = {
            "id": 0,
            "labels": 1,
            "source": 2,
            "title": 3,
        }
        self.card_sort_choice.SetSelection(selection_map.get(self._card_sort_mode, 0))

    def _selected_card_sort_mode(self) -> str:
        selection = self.card_sort_choice.GetSelection()
        if selection == 1:
            return "labels"
        if selection == 2:
            return "source"
        if selection == 3:
            return "title"
        return "id"


    def _coerce_card_label_group_mode(self, value: str | None) -> str:
        if value in {"per_label", "label_set"}:
            return value
        return "per_label"

    def _apply_card_label_group_choice(self) -> None:
        selection_map = {
            "per_label": 0,
            "label_set": 1,
        }
        self.card_label_group_choice.SetSelection(
            selection_map.get(self._card_label_group_mode, 0)
        )

    def _selected_card_label_group_mode(self) -> str:
        selection = self.card_label_group_choice.GetSelection()
        if selection == 1:
            return "label_set"
        return "per_label"

    def _update_label_grouping_state(self) -> None:
        enabled = self._selected_card_sort_mode() == "labels"
        self.card_label_group_label.Enable(enabled)
        self.card_label_group_choice.Enable(enabled)

    def _update_colorize_labels_state(self) -> None:
        enabled = self._current_format() in {ExportFormat.HTML, ExportFormat.DOCX}
        self.colorize_label_backgrounds_checkbox.Enable(enabled)

    def _apply_docx_formula_choice(self) -> None:
        choices = self.docx_formula_choice.GetStrings()
        if not choices:
            return
        selection = 0
        if self._docx_formula_renderer == "mathml":
            selection = 1
        elif self._docx_formula_renderer == "svg":
            selection = 2
        elif self._docx_formula_renderer == "png":
            selection = 3
        elif self._docx_formula_renderer == "text":
            selection = 4
        self.docx_formula_choice.SetSelection(selection)

    def _ensure_extension(self, path: str) -> str:
        if not path:
            return path
        current = self._current_format()
        if current == ExportFormat.HTML:
            suffix = ".html"
        elif current == ExportFormat.DOCX:
            suffix = ".docx"
        elif current == ExportFormat.CSV:
            suffix = ".csv"
        elif current == ExportFormat.TSV:
            suffix = ".tsv"
        else:
            suffix = ".txt"
        target = Path(path)
        if target.suffix.lower() in {".txt", ".html", ".htm", ".docx", ".csv", ".tsv"}:
            return str(target.with_suffix(suffix))
        return path

    def _refresh_path_display(self) -> None:
        path = self.file_picker.GetPath()
        updated = self._ensure_extension(path)
        if updated and updated != path:
            self.file_picker.SetPath(updated)
            path = updated
        self.path_display.ChangeValue(path)

    # ------------------------------------------------------------------
    def _on_path_changed(self, _event: wx.CommandEvent) -> None:
        self._refresh_path_display()
        self._update_ok_state()

    def _on_format_changed(self, _event: wx.CommandEvent) -> None:
        self._refresh_path_display()
        self._update_text_options_visibility()
        self._update_columns_visibility()
        self._update_docx_options_visibility()
        self._update_ok_state()

    def _on_columns_changed(self, _event: wx.CommandEvent) -> None:
        self._update_ok_state()

    def _on_scope_changed(self, _event: wx.CommandEvent) -> None:
        self._update_ok_state()

    def _on_card_sort_changed(self, _event: wx.CommandEvent) -> None:
        self._update_label_grouping_state()

    def _on_docx_heading_toggle(self, _event: wx.CommandEvent) -> None:
        self._update_ok_state()

    def _move_column(self, delta: int) -> None:
        idx = self.column_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        new_idx = idx + delta
        self._reorder_field(idx, new_idx)

    def _reorder_field(self, from_idx: int, to_idx: int) -> None:
        if from_idx == to_idx:
            return
        if from_idx < 0 or from_idx >= len(self._field_order):
            return
        if to_idx < 0 or to_idx >= len(self._field_order):
            return
        checked = set(self._checked_fields())
        field = self._field_order.pop(from_idx)
        self._field_order.insert(to_idx, field)
        self.column_list.Set([self._field_labels[field] for field in self._field_order])
        for i, field in enumerate(self._field_order):
            self.column_list.Check(i, field in checked)
        self.column_list.SetSelection(to_idx)
        self.column_list.SetFocus()
        self._update_ok_state()

    def _on_column_left_down(self, event: wx.MouseEvent) -> None:
        idx = self.column_list.HitTest(event.GetPosition())
        self._drag_start_index = idx if idx != wx.NOT_FOUND else None
        event.Skip()

    def _on_column_left_up(self, event: wx.MouseEvent) -> None:
        if self._drag_start_index is None:
            event.Skip()
            return
        target = self.column_list.HitTest(event.GetPosition())
        if target != wx.NOT_FOUND and target != self._drag_start_index:
            self._reorder_field(self._drag_start_index, target)
        self._drag_start_index = None
        event.Skip()

    def _on_select_all(self, _event: wx.CommandEvent) -> None:
        for idx in range(len(self._field_order)):
            self.column_list.Check(idx, True)
        self._update_ok_state()

    def _on_clear(self, _event: wx.CommandEvent) -> None:
        for idx in range(len(self._field_order)):
            self.column_list.Check(idx, False)
        self._update_ok_state()

    def _on_ok(self, event: wx.CommandEvent) -> None:
        if not self.file_picker.GetPath():
            wx.MessageBox(_("Select export file first."), _("Export blocked"))
            return
        if not self._checked_fields() and not self._can_export_without_columns():
            wx.MessageBox(_("Choose at least one column to export."), _("Export blocked"))
            return
        event.Skip()

    # ------------------------------------------------------------------
    def get_plan(self) -> RequirementExportPlan | None:
        path = self.file_picker.GetPath()
        if not path:
            return None
        columns = self._checked_fields()
        if not columns and not self._can_export_without_columns():
            return None
        docx_renderer = None
        if self._current_format() == ExportFormat.DOCX:
            docx_renderer = "auto"
            if self.docx_formula_choice.GetSelection() == 1:
                docx_renderer = "mathml"
            elif self.docx_formula_choice.GetSelection() == 2:
                docx_renderer = "svg"
            elif self.docx_formula_choice.GetSelection() == 3:
                docx_renderer = "png"
            elif self.docx_formula_choice.GetSelection() == 4:
                docx_renderer = "text"
        return RequirementExportPlan(
            path=Path(path),
            format=self._current_format(),
            columns=columns,
            empty_fields_placeholder=self.txt_empty_fields_checkbox.GetValue(),
            docx_formula_renderer=docx_renderer,
            card_sort_mode=self._selected_card_sort_mode(),
            card_label_group_mode=self._selected_card_label_group_mode(),
            export_scope=self._selected_export_scope(),
            colorize_label_backgrounds=self.colorize_label_backgrounds_checkbox.GetValue(),
            docx_include_requirement_heading=self.docx_include_requirement_heading_checkbox.GetValue(),
        )

    def get_state(self) -> ExportDialogState:
        path = self.file_picker.GetPath() or None
        return ExportDialogState(
            path=path,
            format=self._current_format().value,
            columns=self._checked_fields(),
            order=list(self._field_order),
            empty_fields_placeholder=self.txt_empty_fields_checkbox.GetValue(),
            docx_formula_renderer=(
                "auto"
                if self.docx_formula_choice.GetSelection() == 0
                else "mathml"
                if self.docx_formula_choice.GetSelection() == 1
                else "svg"
                if self.docx_formula_choice.GetSelection() == 2
                else "png"
                if self.docx_formula_choice.GetSelection() == 3
                else "text"
            )
            if self._current_format() == ExportFormat.DOCX
            else self._docx_formula_renderer,
            card_sort_mode=self._selected_card_sort_mode(),
            card_label_group_mode=self._selected_card_label_group_mode(),
            export_scope=self._selected_export_scope(),
            colorize_label_backgrounds=self.colorize_label_backgrounds_checkbox.GetValue(),
            docx_include_requirement_heading=self.docx_include_requirement_heading_checkbox.GetValue(),
        )
