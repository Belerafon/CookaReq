"""Dialog for exporting requirements into text formats."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import wx

from ..config import ExportDialogState
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
    ) -> None:
        title = _("Export Requirements")
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._document_label = document_label or ""
        self._available_fields = self._build_available_fields(available_fields)
        selection_seed = selected_fields
        force_title = True
        if saved_state and saved_state.columns:
            selection_seed = saved_state.columns
            force_title = False
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
            ordered = list(self._default_selected)
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
        self.docx_formula_box = wx.StaticBox(self, label=_("DOCX formulas"))
        self.docx_formula_choice = wx.Choice(
            self.docx_formula_box,
            choices=[
                _("Plain text"),
                _("MathML (LaTeX → MathML → OMML)"),
                _("PNG (LaTeX → PNG)"),
                _("SVG (LaTeX → SVG → PNG)"),
            ],
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
        self.column_list.Bind(wx.EVT_CHECKLISTBOX, self._on_columns_changed)
        self.column_list.Bind(wx.EVT_LEFT_DOWN, self._on_column_left_down)
        self.column_list.Bind(wx.EVT_LEFT_UP, self._on_column_left_up)
        self.move_up_btn.Bind(wx.EVT_BUTTON, lambda _evt: self._move_column(-1))
        self.move_down_btn.Bind(wx.EVT_BUTTON, lambda _evt: self._move_column(1))
        self.select_all_btn.Bind(wx.EVT_BUTTON, self._on_select_all)
        self.clear_btn.Bind(wx.EVT_BUTTON, self._on_clear)
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

        txt_options_sizer = wx.StaticBoxSizer(self.txt_options_box, wx.VERTICAL)
        txt_options_sizer.Add(self.txt_empty_fields_checkbox, 0, wx.ALL, 6)
        main_sizer.Add(txt_options_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)

        docx_options_sizer = wx.StaticBoxSizer(self.docx_formula_box, wx.VERTICAL)
        docx_options_sizer.Add(self.docx_formula_choice, 0, wx.ALL, 6)
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
        require_columns = self._current_format() in {
            ExportFormat.TXT,
            ExportFormat.CSV,
            ExportFormat.TSV,
        }
        has_columns = bool(self._checked_fields()) if require_columns else True
        self.ok_button.Enable(has_path and has_columns)

    def _update_text_options_visibility(self) -> None:
        show_options = self._current_format() in {
            ExportFormat.TXT,
            ExportFormat.HTML,
            ExportFormat.DOCX,
        }
        self._main_sizer.Show(self._txt_options_sizer, show_options, recursive=True)
        self._main_sizer.Layout()

    def _update_columns_visibility(self) -> None:
        show_columns = self._current_format() in {
            ExportFormat.TXT,
            ExportFormat.CSV,
            ExportFormat.TSV,
        }
        self._main_sizer.Show(self._columns_sizer, show_columns, recursive=True)
        self._main_sizer.Layout()

    def _update_docx_options_visibility(self) -> None:
        is_docx = self._current_format() == ExportFormat.DOCX
        self._main_sizer.Show(self._docx_options_sizer, is_docx, recursive=True)
        self._main_sizer.Layout()

    def _apply_docx_formula_choice(self) -> None:
        choices = self.docx_formula_choice.GetStrings()
        if not choices:
            return
        selection = 0
        if self._docx_formula_renderer == "mathml":
            selection = 1
        elif self._docx_formula_renderer == "png":
            selection = 2
        elif self._docx_formula_renderer == "svg":
            selection = 3
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
        if self._current_format() in {
            ExportFormat.TXT,
            ExportFormat.CSV,
            ExportFormat.TSV,
        } and not self._checked_fields():
            wx.MessageBox(_("Choose at least one column to export."), _("Export blocked"))
            return
        event.Skip()

    # ------------------------------------------------------------------
    def get_plan(self) -> RequirementExportPlan | None:
        path = self.file_picker.GetPath()
        if not path:
            return None
        columns = self._checked_fields()
        if (
            not columns
            and self._current_format()
            in {
                ExportFormat.TXT,
                ExportFormat.CSV,
                ExportFormat.TSV,
            }
        ):
            return None
        docx_renderer = None
        if self._current_format() == ExportFormat.DOCX:
            docx_renderer = "text"
            if self.docx_formula_choice.GetSelection() == 1:
                docx_renderer = "mathml"
            elif self.docx_formula_choice.GetSelection() == 2:
                docx_renderer = "png"
            elif self.docx_formula_choice.GetSelection() == 3:
                docx_renderer = "svg"
        return RequirementExportPlan(
            path=Path(path),
            format=self._current_format(),
            columns=columns,
            empty_fields_placeholder=self.txt_empty_fields_checkbox.GetValue(),
            docx_formula_renderer=docx_renderer,
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
                "mathml"
                if self.docx_formula_choice.GetSelection() == 1
                else "png"
                if self.docx_formula_choice.GetSelection() == 2
                else "svg"
                if self.docx_formula_choice.GetSelection() == 3
                else "text"
            )
            if self._current_format() == ExportFormat.DOCX
            else self._docx_formula_renderer,
        )
