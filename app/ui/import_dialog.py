"""Dialog for configuring requirement import from CSV and TSV files."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re
from collections.abc import Iterable

import wx
import wx.grid as gridlib

from ..core.requirement_import import (
    ImportFieldSpec,
    RequirementImportConfiguration,
    RequirementImportError,
    RequirementImportResult,
    SequentialIDAllocator,
    TabularDataset,
    build_requirements,
    detect_format,
    importable_fields,
    load_csv_dataset,
)
from ..i18n import _
from ..log import logger
from . import locale


@dataclass(slots=True)
class RequirementImportPlan:
    """Configuration collected from the dialog for later execution."""

    path: Path
    dataset: TabularDataset
    configuration: RequirementImportConfiguration
    delimiter: str


class RequirementImportDialog(wx.Dialog):
    """Allow the user to map spreadsheet columns to requirement fields."""

    PREVIEW_LIMIT = 20

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        existing_ids: Iterable[int],
        next_id: int,
        document_label: str | None = None,
    ) -> None:
        """Initialise dialog state and construct interactive controls."""
        title = _("Import Requirements")
        super().__init__(parent, title=title, style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self._base_allocator = SequentialIDAllocator(start=next_id, existing=existing_ids)
        self._document_label = document_label or ""
        self._selected_path: Path | None = None
        self._dataset: TabularDataset | None = None
        self._delimiter = ","
        self._current_config: RequirementImportConfiguration | None = None
        self._current_preview: RequirementImportResult | None = None
        self._auto_mapping = True
        self._is_updating_mapping = False
        self._column_aliases = self._build_aliases()

        self._create_controls()
        self._bind_events()
        self._arrange_layout()
        self.SetMinSize(self.GetSize())

    # ------------------------------------------------------------------
    def _create_controls(self) -> None:
        self.file_picker = wx.FilePickerCtrl(
            self,
            message=_("Select CSV file"),
            wildcard=_("CSV and TSV files (*.csv;*.tsv)|*.csv;*.tsv|All files|*.*"),
        )
        self.delimiter_label = wx.StaticText(self, label=_("Field delimiter"))
        self.delimiter_ctrl = wx.TextCtrl(self, value=self._delimiter, size=(60, -1))
        self.header_checkbox = wx.CheckBox(self, label=_("First row is a header"))
        self.header_checkbox.SetValue(True)

        self.mapping_box = wx.StaticBox(self, label=_("Column mapping"))
        self.mapping_panel = wx.ScrolledWindow(self.mapping_box, style=wx.VSCROLL)
        self.mapping_panel.SetScrollRate(0, 10)
        self.mapping_sizer = wx.FlexGridSizer(cols=2, hgap=8, vgap=6)
        self.mapping_sizer.AddGrowableCol(1, 1)
        self.mapping_panel.SetSizer(self.mapping_sizer)
        self.mapping_controls: dict[str, wx.Choice] = {}
        for spec in importable_fields:
            self._add_mapping_control(spec)

        self.preview_box = wx.StaticBox(self, label=_("Preview"))
        self.preview_grid = gridlib.Grid(self.preview_box)
        self.preview_grid.CreateGrid(0, 0)
        self.preview_grid.EnableEditing(False)
        self.preview_grid.EnableDragRowSize(False)
        self.preview_grid.EnableDragColSize(True)
        self.preview_grid.SetMargins(0, 0)
        self.preview_grid.SetMinSize((500, 200))

        self.summary_text = wx.StaticText(self, label="")
        self.summary_text.SetLabelMarkup(_("<i>Select a file to preview data.</i>"))
        self.error_text = wx.TextCtrl(
            self,
            value="",
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.BORDER_SIMPLE,
        )
        self.error_text.Hide()

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
        if self.ok_button:
            self.ok_button.Enable(False)
        self.button_sizer = buttons

    def _bind_events(self) -> None:
        self.file_picker.Bind(wx.EVT_FILEPICKER_CHANGED, self._on_file_selected)
        self.delimiter_ctrl.Bind(wx.EVT_TEXT, self._on_delimiter_changed)
        self.header_checkbox.Bind(wx.EVT_CHECKBOX, self._on_header_toggled)
        for choice in self.mapping_controls.values():
            choice.Bind(wx.EVT_CHOICE, self._on_mapping_changed)

    def _arrange_layout(self) -> None:
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        if self._document_label:
            doc_text = wx.StaticText(
                self,
                label=_("Target document: {label}").format(label=self._document_label),
            )
            main_sizer.Add(doc_text, 0, wx.BOTTOM, 6)

        file_sizer = wx.FlexGridSizer(cols=3, hgap=8, vgap=6)
        file_sizer.AddGrowableCol(0, 1)
        file_sizer.Add(self.file_picker, 0, wx.EXPAND)
        file_sizer.Add(self.delimiter_label, 0, wx.ALIGN_CENTER_VERTICAL)
        file_sizer.Add(self.delimiter_ctrl, 0, wx.ALIGN_CENTER_VERTICAL)
        file_sizer.Add((0, 0))
        file_sizer.Add(self.header_checkbox, 0, wx.ALIGN_CENTER_VERTICAL)
        file_sizer.Add((0, 0))
        main_sizer.Add(file_sizer, 0, wx.EXPAND | wx.ALL, 10)

        mapping_sizer = wx.StaticBoxSizer(self.mapping_box, wx.VERTICAL)
        mapping_sizer.Add(self.mapping_panel, 1, wx.EXPAND | wx.ALL, 6)
        main_sizer.Add(mapping_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        preview_sizer = wx.StaticBoxSizer(self.preview_box, wx.VERTICAL)
        preview_sizer.Add(self.preview_grid, 1, wx.EXPAND)
        main_sizer.Add(preview_sizer, 1, wx.EXPAND | wx.ALL, 10)

        main_sizer.Add(self.summary_text, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        main_sizer.Add(self.error_text, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        if self.button_sizer:
            main_sizer.Add(self.button_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 10)

        self.SetSizer(main_sizer)
        self.Layout()

    # ------------------------------------------------------------------
    def _build_aliases(self) -> dict[str, set[str]]:
        aliases: dict[str, set[str]] = {}
        for spec in importable_fields:
            names = {self._normalize_name(spec.name)}
            names.update(self._normalize_name(alias) for alias in spec.synonyms)
            aliases[spec.name] = {name for name in names if name}
        return aliases

    @staticmethod
    def _normalize_name(name: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
        return normalized

    def _add_mapping_control(self, spec: ImportFieldSpec) -> None:
        label = locale.field_label(spec.name)
        if spec.required:
            label = f"{label} *"
        text = wx.StaticText(self.mapping_panel, label=label)
        choice = wx.Choice(self.mapping_panel)
        choice.Enable(False)
        self.mapping_sizer.Add(text, 0, wx.ALIGN_CENTER_VERTICAL)
        self.mapping_sizer.Add(choice, 1, wx.EXPAND)
        self.mapping_controls[spec.name] = choice

    # ------------------------------------------------------------------
    def _on_file_selected(self, event: wx.CommandEvent) -> None:
        path = Path(event.GetPath()) if event.GetPath() else None
        if not path or not path.exists():
            self._show_error(None)
            self._clear_dataset()
            return
        try:
            detect_format(path)
        except RequirementImportError as exc:
            self._show_error(str(exc))
            self._clear_dataset()
            return
        self._selected_path = path
        self._auto_mapping = True
        self._load_dataset()
        self.Layout()

    def _on_delimiter_changed(self, _event: wx.CommandEvent) -> None:
        value = self.delimiter_ctrl.GetValue()
        self._delimiter = value or ","
        self._load_dataset()

    def _on_header_toggled(self, _event: wx.CommandEvent) -> None:
        self._update_mapping_options()
        self._refresh_preview()

    def _on_mapping_changed(self, _event: wx.CommandEvent) -> None:
        if self._is_updating_mapping:
            return
        self._auto_mapping = False
        self._refresh_preview()

    # ------------------------------------------------------------------
    def _load_dataset(self) -> None:
        if not self._selected_path:
            return
        try:
            dataset = load_csv_dataset(self._selected_path, delimiter=self._delimiter or ",")
        except RequirementImportError as exc:
            logger.warning("Failed to load import dataset: %s", exc)
            self._show_error(str(exc))
            self._clear_dataset()
            return
        self._dataset = dataset
        self._show_error(None)
        self._update_mapping_options()
        self._refresh_preview()

    def _clear_dataset(self) -> None:
        self._dataset = None
        self._current_config = None
        self._current_preview = None
        self._update_mapping_controls(enabled=False)
        self._clear_grid()
        self._update_summary(None)
        if self.ok_button:
            self.ok_button.Enable(False)

    def _update_mapping_options(self) -> None:
        dataset = self._dataset
        if dataset is None:
            self._update_mapping_controls(enabled=False)
            return
        column_names = dataset.column_names(use_header=self.header_checkbox.GetValue())
        self._is_updating_mapping = True
        try:
            for field, choice in self.mapping_controls.items():
                choice.Enable(True)
                choice.Clear()
                self._populate_choice(field, choice, column_names)
            if self._auto_mapping:
                self._apply_auto_mapping(column_names)
        finally:
            self._is_updating_mapping = False
        self.mapping_panel.Layout()
        self.mapping_panel.FitInside()

    def _populate_choice(
        self, field: str, choice: wx.Choice, column_names: list[str]
    ) -> None:
        ignore_label = _("(Ignore)")
        auto_label = _("(Auto)")
        choice.Append(ignore_label, clientData=None)
        if field == "id":
            choice.Append(auto_label, clientData=-1)
        for index, name in enumerate(column_names):
            label = f"{index + 1}. {name}" if name else f"{index + 1}."
            choice.Append(label, clientData=index)
        choice.SetSelection(0)

    def _apply_auto_mapping(self, column_names: list[str]) -> None:
        assignments: dict[str, int | None] = {}
        used: set[int] = set()
        normalized_columns = [self._normalize_name(name) for name in column_names]
        for spec in importable_fields:
            target_set = self._column_aliases.get(spec.name, set())
            selected_index: int | None = None
            for idx, normalized in enumerate(normalized_columns):
                if idx in used:
                    continue
                if not normalized:
                    continue
                if normalized in target_set:
                    selected_index = idx
                    break
            if selected_index is None and spec.required and normalized_columns:
                selected_index = 0 if 0 not in used else None
            assignments[spec.name] = selected_index
            if selected_index is not None:
                used.add(selected_index)
        self._is_updating_mapping = True
        try:
            for field, choice in self.mapping_controls.items():
                desired = assignments.get(field)
                if desired is None:
                    choice.SetSelection(0)
                    continue
                for idx in range(choice.GetCount()):
                    if choice.GetClientData(idx) == desired:
                        choice.SetSelection(idx)
                        break
        finally:
            self._is_updating_mapping = False

    def _update_mapping_controls(self, *, enabled: bool) -> None:
        for choice in self.mapping_controls.values():
            choice.Enable(enabled)

    # ------------------------------------------------------------------
    def _refresh_preview(self) -> None:
        dataset = self._dataset
        if dataset is None:
            self._clear_grid()
            self._update_summary(None)
            if self.ok_button:
                self.ok_button.Enable(False)
            return
        mapping = self._collect_mapping()
        if mapping is None:
            self._clear_grid()
            self._update_summary(None)
            if self.ok_button:
                self.ok_button.Enable(False)
            return
        try:
            config = RequirementImportConfiguration(
                mapping=mapping,
                has_header=self.header_checkbox.GetValue(),
            )
        except RequirementImportError as exc:
            self._show_error(str(exc))
            self._clear_grid()
            if self.ok_button:
                self.ok_button.Enable(False)
            return
        preview_allocator = self._base_allocator.clone()
        result = build_requirements(
            dataset,
            config,
            allocator=preview_allocator,
            max_rows=self.PREVIEW_LIMIT,
        )
        self._current_config = config
        self._current_preview = result
        self._populate_grid(result.requirements, config)
        total_rows = dataset.row_count(skip_header=config.has_header)
        self._update_summary(result, total_rows)
        issues_present = bool(result.issues)
        has_items = bool(result.requirements)
        if issues_present:
            messages = [
                _("Row {row}: {message}").format(row=issue.row, message=issue.message)
                if issue.field is None
                else _("Row {row}, field {field}: {message}").format(
                    row=issue.row, field=issue.field, message=issue.message
                )
                for issue in result.issues[:5]
            ]
            if len(result.issues) > 5:
                messages.append(
                    _("{count} more issue(s) not shown").format(
                        count=len(result.issues) - 5
                    )
                )
            self.error_text.SetValue("\n".join(messages))
            self.error_text.Show()
        else:
            self.error_text.Hide()
            self.error_text.SetValue("")
        if self.ok_button:
            self.ok_button.Enable(has_items and not issues_present)
        self.Layout()

    def _collect_mapping(self) -> dict[str, int | None] | None:
        mapping: dict[str, int | None] = {}
        for field, choice in self.mapping_controls.items():
            selection = choice.GetSelection()
            if selection == wx.NOT_FOUND:
                mapping[field] = None
                continue
            client = choice.GetClientData(selection)
            if isinstance(client, int) and client >= 0:
                mapping[field] = client
            elif isinstance(client, int) and client == -1:
                mapping[field] = None
            else:
                mapping[field] = None
        return mapping

    def _clear_grid(self) -> None:
        if not self.preview_grid:
            return
        rows = self.preview_grid.GetNumberRows()
        cols = self.preview_grid.GetNumberCols()
        if rows:
            self.preview_grid.DeleteRows(0, rows)
        if cols:
            self.preview_grid.DeleteCols(0, cols)
        self.preview_grid.ForceRefresh()

    def _populate_grid(
        self, requirements: list, config: RequirementImportConfiguration
    ) -> None:
        self._clear_grid()
        if not requirements:
            return
        fields_to_show = [spec.name for spec in importable_fields if spec.name in config.mapping]
        if "id" not in fields_to_show:
            fields_to_show.insert(0, "id")
        cols = len(fields_to_show)
        rows = len(requirements)
        self.preview_grid.AppendCols(cols)
        self.preview_grid.AppendRows(rows)
        for col, field in enumerate(fields_to_show):
            label = locale.field_label(field)
            self.preview_grid.SetColLabelValue(col, label)
        for row_idx, requirement in enumerate(requirements):
            for col_idx, field in enumerate(fields_to_show):
                value = getattr(requirement, field, "")
                if isinstance(value, Enum):
                    text = locale.code_to_label(field, value.value)
                elif isinstance(value, list):
                    text = ", ".join(str(item) for item in value)
                elif isinstance(value, wx.DateTime):  # pragma: no cover - wx specific
                    text = value.FormatISODate()
                else:
                    text = str(value)
                self.preview_grid.SetCellValue(row_idx, col_idx, text)
        self.preview_grid.AutoSizeColumns(False)

    def _update_summary(
        self, result: RequirementImportResult | None, total_rows: int | None = None
    ) -> None:
        if result is None or total_rows is None:
            self.summary_text.SetLabelMarkup(
                _("<i>Select a file to preview data.</i>")
            )
            return
        imported = result.imported_rows
        issues = len(result.issues)
        skipped = result.skipped_rows
        if result.truncated and total_rows is not None:
            preview_info = _("Showing first {count} row(s)").format(
                count=self.PREVIEW_LIMIT
            )
        else:
            preview_info = ""
        summary = _(
            "Ready to import {imported} requirement(s) from {total} data row(s). Skipped {skipped}."
        ).format(imported=imported, total=total_rows, skipped=skipped)
        if issues:
            summary += " " + _("Found {count} issue(s).").format(count=issues)
        if preview_info:
            summary += f" {preview_info}."
        self.summary_text.SetLabel(summary)

    def _show_error(self, message: str | None) -> None:
        if message:
            self.summary_text.SetLabel(message)
        else:
            self.summary_text.SetLabelMarkup(
                _("<i>Select a file to preview data.</i>")
            )

    # ------------------------------------------------------------------
    def get_plan(self) -> RequirementImportPlan | None:
        """Return configured import plan or ``None`` when selection incomplete."""
        if not (self._dataset and self._current_config and self._selected_path):
            return None
        return RequirementImportPlan(
            path=self._selected_path,
            dataset=self._dataset,
            configuration=self._current_config,
            delimiter=self._delimiter or ",",
        )

