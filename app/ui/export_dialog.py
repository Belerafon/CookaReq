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
    CSV = "csv"
    TSV = "tsv"


@dataclass(slots=True)
class RequirementExportPlan:
    """Configuration collected from the export dialog."""

    path: Path
    format: ExportFormat
    columns: list[str]


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
        self._refresh_checklist()
        self._update_ok_state()
        self.SetSize((820, 620))
        self.SetMinSize(self.GetSize())

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
            ExportFormat.CSV: 2,
            ExportFormat.TSV: 3,
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
                "CSV files (*.csv)|*.csv|TSV files (*.tsv)|*.tsv|All files|*.*"
            ),
            style=wx.FLP_SAVE | wx.FLP_OVERWRITE_PROMPT,
        )

        self.format_choice = wx.RadioBox(
            self,
            label=_("Export format"),
            choices=[
                _("Plain text (.txt)"),
                _("HTML (.html)"),
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
        main_sizer.Add(self.format_choice, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

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
            return ExportFormat.CSV
        if selection == 3:
            return ExportFormat.TSV
        return ExportFormat.TXT

    def _update_ok_state(self) -> None:
        if not self.ok_button:
            return
        path = self.file_picker.GetPath()
        has_path = bool(path)
        has_columns = bool(self._checked_fields())
        self.ok_button.Enable(has_path and has_columns)

    def _ensure_extension(self, path: str) -> str:
        if not path:
            return path
        current = self._current_format()
        if current == ExportFormat.HTML:
            suffix = ".html"
        elif current == ExportFormat.CSV:
            suffix = ".csv"
        elif current == ExportFormat.TSV:
            suffix = ".tsv"
        else:
            suffix = ".txt"
        target = Path(path)
        if target.suffix.lower() in {".txt", ".html", ".htm", ".csv", ".tsv"}:
            return str(target.with_suffix(suffix))
        return path

    # ------------------------------------------------------------------
    def _on_path_changed(self, _event: wx.CommandEvent) -> None:
        self._update_ok_state()

    def _on_format_changed(self, _event: wx.CommandEvent) -> None:
        current = self.file_picker.GetPath()
        updated = self._ensure_extension(current)
        if current and updated != current:
            self.file_picker.SetPath(updated)
        self._update_ok_state()

    def _on_columns_changed(self, _event: wx.CommandEvent) -> None:
        self._update_ok_state()

    def _move_column(self, delta: int) -> None:
        idx = self.column_list.GetSelection()
        if idx == wx.NOT_FOUND:
            return
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(self._field_order):
            return
        checked = set(self._checked_fields())
        self._field_order[idx], self._field_order[new_idx] = (
            self._field_order[new_idx],
            self._field_order[idx],
        )
        self.column_list.SetSelection(new_idx)
        self.column_list.Set([self._field_labels[field] for field in self._field_order])
        for i, field in enumerate(self._field_order):
            self.column_list.Check(i, field in checked)
        self._update_ok_state()

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
        if not self._checked_fields():
            wx.MessageBox(_("Choose at least one column to export."), _("Export blocked"))
            return
        event.Skip()

    # ------------------------------------------------------------------
    def get_plan(self) -> RequirementExportPlan | None:
        path = self.file_picker.GetPath()
        if not path:
            return None
        columns = self._checked_fields()
        if not columns:
            return None
        return RequirementExportPlan(
            path=Path(path),
            format=self._current_format(),
            columns=columns,
        )

    def get_state(self) -> ExportDialogState:
        path = self.file_picker.GetPath() or None
        return ExportDialogState(
            path=path,
            format=self._current_format().value,
            columns=self._checked_fields(),
            order=list(self._field_order),
        )
