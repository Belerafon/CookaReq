"""Graphical traceability matrix viewer."""
from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from collections.abc import Mapping

import wx
import wx.grid as gridlib

from ..services.requirements import Document
from ..core.trace_matrix import (
    TraceDirection,
    TraceMatrix,
    TraceMatrixAxisConfig,
    TraceMatrixCell,
    TraceMatrixConfig,
)
from ..i18n import _

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from .controllers.documents import DocumentsController


_FIELD_CHOICES: tuple[str, ...] = (
    "rid",
    "title",
    "status",
    "type",
    "owner",
    "verification",
    "revision",
    "modified_at",
    "labels",
)


@dataclass(frozen=True)
class TraceMatrixDisplayOptions:
    """Presentation options selected by the user for matrix rendering/export."""

    row_sort_field: str = "rid"
    column_sort_field: str = "rid"
    selected_fields: tuple[str, ...] = ("rid", "title", "status", "verification", "owner")
    compact_symbols: bool = True
    hide_unlinked: bool = False


@dataclass(frozen=True)
class TraceMatrixViewPlan:
    """Full plan returned by the config dialog."""

    config: TraceMatrixConfig
    options: TraceMatrixDisplayOptions
    output_format: str = "interactive"


def _format_document_label(doc: Document) -> str:
    title = doc.title.strip()
    if not title:
        return doc.prefix
    if title == doc.prefix:
        return title
    return f"{doc.prefix} — {title}"


def _field_label(key: str) -> str:
    labels = {
        "rid": _("RID"),
        "title": _("Title"),
        "status": _("Status"),
        "type": _("Type"),
        "owner": _("Owner"),
        "verification": _("Verification"),
        "revision": _("Revision"),
        "modified_at": _("Modified At"),
        "labels": _("Labels"),
    }
    return labels.get(key, key)


def _entry_field_value(entry, field: str) -> str:
    req = entry.requirement
    if field == "rid":
        return req.rid
    value = getattr(req, field, "")
    if hasattr(value, "value"):
        value = value.value
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _build_axis_line(entry, selected_fields: tuple[str, ...]) -> str:
    lines = [_entry_field_value(entry, field) for field in selected_fields]
    filtered = [line for line in lines if line.strip()]
    return "\n".join(filtered)


def apply_display_options(matrix: TraceMatrix, options: TraceMatrixDisplayOptions) -> TraceMatrix:
    """Return matrix reordered/filtered according to ``options``."""

    rows = tuple(sorted(matrix.rows, key=lambda entry: _entry_field_value(entry, options.row_sort_field)))
    columns = tuple(
        sorted(matrix.columns, key=lambda entry: _entry_field_value(entry, options.column_sort_field))
    )

    if options.hide_unlinked:
        rows = tuple(
            row for row in rows if any(matrix.cells.get((row.rid, column.rid)) for column in columns)
        )
        columns = tuple(
            column for column in columns if any(matrix.cells.get((row.rid, column.rid)) for row in rows)
        )

    return TraceMatrix(
        config=matrix.config,
        direction=matrix.direction,
        rows=rows,
        columns=columns,
        cells=matrix.cells,
        summary=matrix.summary,
        documents=matrix.documents,
    )


class TraceMatrixConfigDialog(wx.Dialog):
    """Collect trace matrix config and display options from the user."""

    def __init__(
        self,
        parent: wx.Window | None,
        documents: Mapping[str, Document],
        *,
        default_rows: str | None = None,
        default_columns: str | None = None,
        direction: TraceDirection = TraceDirection.CHILD_TO_PARENT,
    ) -> None:
        if not documents:
            raise ValueError("documents cannot be empty")

        super().__init__(parent, title=_("Trace Matrix Configuration"), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.SetEscapeId(wx.ID_CANCEL)

        self._documents = documents
        self._direction = direction
        self._prefixes = sorted(documents)

        choices = [_format_document_label(documents[prefix]) for prefix in self._prefixes]

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        form = wx.FlexGridSizer(rows=4, cols=2, hgap=8, vgap=8)
        form.AddGrowableCol(1, proportion=1)

        form.Add(wx.StaticText(self, label=_("Rows document")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._rows_choice = wx.Choice(self, choices=choices)
        form.Add(self._rows_choice, 1, wx.EXPAND)

        form.Add(wx.StaticText(self, label=_("Columns document")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._columns_choice = wx.Choice(self, choices=choices)
        form.Add(self._columns_choice, 1, wx.EXPAND)

        sort_choices = [_field_label(field) for field in _FIELD_CHOICES]
        form.Add(wx.StaticText(self, label=_("Rows sort field")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._rows_sort = wx.Choice(self, choices=sort_choices)
        form.Add(self._rows_sort, 1, wx.EXPAND)

        form.Add(wx.StaticText(self, label=_("Columns sort field")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._columns_sort = wx.Choice(self, choices=sort_choices)
        form.Add(self._columns_sort, 1, wx.EXPAND)

        padding = self.FromDIP(12)
        main_sizer.Add(form, 0, wx.ALL | wx.EXPAND, padding)

        options_box = wx.StaticBoxSizer(wx.VERTICAL, self, _("Display and export options"))

        self._compact_symbols = wx.CheckBox(options_box.GetStaticBox(), label=_("Use compact cell symbols (·/✓/!)"))
        self._compact_symbols.SetValue(True)
        options_box.Add(self._compact_symbols, 0, wx.ALL | wx.EXPAND, self.FromDIP(6))

        self._hide_unlinked = wx.CheckBox(options_box.GetStaticBox(), label=_("Hide unlinked rows/columns"))
        options_box.Add(self._hide_unlinked, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(6))

        output_row = wx.BoxSizer(wx.HORIZONTAL)
        output_row.Add(wx.StaticText(options_box.GetStaticBox(), label=_("Output format")), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, self.FromDIP(8))
        self._output_format = wx.Choice(options_box.GetStaticBox(), choices=[_("Interactive matrix window"), "matrix-html", "matrix-csv", "matrix-json"])
        self._output_format.SetSelection(0)
        output_row.Add(self._output_format, 1, wx.EXPAND)
        options_box.Add(output_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(6))

        options_box.Add(wx.StaticText(options_box.GetStaticBox(), label=_("Requirement card fields (headers/details/export)")), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(6))
        self._fields = wx.CheckListBox(options_box.GetStaticBox(), choices=[_field_label(field) for field in _FIELD_CHOICES])
        for idx, field in enumerate(_FIELD_CHOICES):
            if field in {"rid", "title", "status", "verification", "owner"}:
                self._fields.Check(idx, True)
        options_box.Add(self._fields, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(6))

        main_sizer.Add(options_box, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, padding)

        button_sizer = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if button_sizer is not None:
            main_sizer.Add(button_sizer, 0, wx.ALL | wx.EXPAND, padding)

        self.SetSizer(main_sizer)
        self.SetMinSize((self.FromDIP(640), self.FromDIP(620)))
        self.Fit()
        self.CentreOnParent()

        self._select_default(self._rows_choice, default_rows)
        self._select_default(self._columns_choice, default_columns)
        self._rows_sort.SetSelection(0)
        self._columns_sort.SetSelection(0)

        if self._columns_choice.GetSelection() == wx.NOT_FOUND:
            row_index = self._rows_choice.GetSelection()
            fallback = 0
            if row_index != wx.NOT_FOUND and len(self._prefixes) > 1:
                fallback = (row_index + 1) % len(self._prefixes)
            self._columns_choice.SetSelection(fallback)

        ok_button = self.FindWindowById(wx.ID_OK)
        if isinstance(ok_button, wx.Button):
            ok_button.SetDefault()

    def _select_default(self, choice: wx.Choice, prefix: str | None) -> None:
        if prefix and prefix in self._prefixes:
            choice.SetSelection(self._prefixes.index(prefix))
        elif self._prefixes:
            choice.SetSelection(0)

    def get_config(self) -> TraceMatrixConfig:
        row_index = self._rows_choice.GetSelection()
        column_index = self._columns_choice.GetSelection()
        if row_index == wx.NOT_FOUND or column_index == wx.NOT_FOUND:
            raise RuntimeError("TraceMatrixConfigDialog used before selections were made")
        row_prefix = self._prefixes[row_index]
        column_prefix = self._prefixes[column_index]
        return TraceMatrixConfig(
            rows=TraceMatrixAxisConfig(documents=(row_prefix,)),
            columns=TraceMatrixAxisConfig(documents=(column_prefix,)),
            direction=self._direction,
        )

    def get_plan(self) -> TraceMatrixViewPlan:
        config = self.get_config()
        row_sort_field = _FIELD_CHOICES[self._rows_sort.GetSelection()]
        column_sort_field = _FIELD_CHOICES[self._columns_sort.GetSelection()]
        selected_fields = tuple(
            field for idx, field in enumerate(_FIELD_CHOICES) if self._fields.IsChecked(idx)
        )
        if not selected_fields:
            selected_fields = ("rid", "title")
        format_index = self._output_format.GetSelection()
        output_format = "interactive" if format_index == 0 else self._output_format.GetString(format_index)

        return TraceMatrixViewPlan(
            config=config,
            options=TraceMatrixDisplayOptions(
                row_sort_field=row_sort_field,
                column_sort_field=column_sort_field,
                selected_fields=selected_fields,
                compact_symbols=self._compact_symbols.GetValue(),
                hide_unlinked=self._hide_unlinked.GetValue(),
            ),
            output_format=output_format,
        )


class TraceMatrixTable(gridlib.GridTableBase):
    """Virtual table exposing :class:`TraceMatrix` data to :class:`wx.grid.Grid`."""

    _LINK_SYMBOL = "\u25CF"

    def __init__(self, matrix: TraceMatrix, *, compact_symbols: bool = True) -> None:
        super().__init__()
        self.update_matrix(matrix)
        self._link_colour = wx.Colour(102, 187, 106)
        self._link_text_colour = wx.Colour(32, 32, 32)
        self._compact_symbols = compact_symbols

    def update_matrix(self, matrix: TraceMatrix) -> None:
        self.matrix = matrix
        self.rows = matrix.rows
        self.columns = matrix.columns
        self.cells = matrix.cells

    def GetNumberRows(self) -> int:  # noqa: N802 - wx naming
        return len(self.rows)

    def GetNumberCols(self) -> int:  # noqa: N802 - wx naming
        return len(self.columns)

    def IsEmptyCell(self, row: int, col: int) -> bool:  # noqa: N802 - wx naming
        return not self._get_cell(row, col)

    def GetValue(self, row: int, col: int) -> str:  # noqa: N802 - wx naming
        cell = self._get_cell(row, col)
        if not cell:
            return "·" if self._compact_symbols else ""
        if self._compact_symbols:
            return "!" if cell.suspect else "✓"
        count = len(cell.links)
        return self._LINK_SYMBOL if count == 1 else str(count)

    def GetAttr(self, row: int, col: int, kind: int) -> gridlib.GridCellAttr | None:  # noqa: N802
        cell = self._get_cell(row, col)
        attr = gridlib.GridCellAttr()
        attr.SetReadOnly(True)
        if cell:
            attr.SetBackgroundColour(self._link_colour)
            attr.SetTextColour(self._link_text_colour)
            attr.SetAlignment(wx.ALIGN_CENTER, wx.ALIGN_CENTER)
        attr.IncRef()
        return attr

    def GetRowLabelValue(self, row: int) -> str:  # noqa: N802 - wx naming
        entry = self.rows[row]
        return _format_label(entry)

    def GetColLabelValue(self, col: int) -> str:  # noqa: N802 - wx naming
        entry = self.columns[col]
        return _format_label(entry)

    def _get_cell(self, row: int, col: int) -> TraceMatrixCell | None:
        if row < 0 or col < 0:
            return None
        if row >= len(self.rows) or col >= len(self.columns):
            return None
        key = (self.rows[row].rid, self.columns[col].rid)
        return self.cells.get(key)


def _format_label(entry) -> str:
    requirement = entry.requirement
    document = entry.document
    title = requirement.title.strip() or _("(untitled)")
    doc_title = document.title.strip() or document.prefix
    if doc_title == document.prefix:
        doc_line = document.prefix
    else:
        doc_line = f"{document.prefix} — {doc_title}"
    return "\n".join((requirement.rid, title, doc_line))


@dataclass
class _DetailsState:
    row_label: str = ""
    column_label: str = ""
    link_details: str = ""


class TraceMatrixDetailsPanel(wx.Panel):
    """Display contextual information about the current selection."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent)
        self._build_ui()
        self.show_message(_("Select a cell or header to view details."))

    def _build_ui(self) -> None:
        padding = self.FromDIP(12)
        root = wx.BoxSizer(wx.VERTICAL)

        self._message = wx.StaticText(self, label="")
        root.Add(self._message, 0, wx.ALL | wx.EXPAND, padding)

        self._row_box = wx.StaticBoxSizer(wx.VERTICAL, self, _("Row"))
        self._row_text = wx.StaticText(self._row_box.GetStaticBox(), label="")
        self._row_box.Add(self._row_text, 0, wx.ALL | wx.EXPAND, padding)
        root.Add(self._row_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, padding)

        self._column_box = wx.StaticBoxSizer(wx.VERTICAL, self, _("Column"))
        self._column_text = wx.StaticText(self._column_box.GetStaticBox(), label="")
        self._column_box.Add(self._column_text, 0, wx.ALL | wx.EXPAND, padding)
        root.Add(self._column_box, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, padding)

        self._links_box = wx.StaticBoxSizer(wx.VERTICAL, self, _("Links"))
        self._links_text = wx.StaticText(self._links_box.GetStaticBox(), label="")
        self._links_box.Add(self._links_text, 0, wx.ALL | wx.EXPAND, padding)
        root.Add(self._links_box, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, padding)

        self.SetSizer(root)

    def show_message(self, text: str) -> None:
        self._message.SetLabel(text)
        self._row_box.ShowItems(False)
        self._column_box.ShowItems(False)
        self._links_box.ShowItems(False)
        self.Layout()

    def show_state(self, state: _DetailsState) -> None:
        self._message.SetLabel("")
        self._row_box.ShowItems(True)
        self._column_box.ShowItems(True)
        self._links_box.ShowItems(True)

        self._row_text.SetLabel(state.row_label)
        self._row_text.Wrap(self.FromDIP(260))
        self._column_text.SetLabel(state.column_label)
        self._column_text.Wrap(self.FromDIP(260))
        self._links_text.SetLabel(state.link_details)
        self._links_text.Wrap(self.FromDIP(260))
        self.Layout()


class TraceMatrixFrame(wx.Frame):
    """Interactive traceability matrix window."""

    def __init__(
        self,
        parent: wx.Window | None,
        controller: DocumentsController,
        config: TraceMatrixConfig,
        matrix: TraceMatrix,
        options: TraceMatrixDisplayOptions | None = None,
    ) -> None:
        super().__init__(parent, title=_("Trace Matrix"))
        self.controller = controller
        self.config = config
        self.options = options or TraceMatrixDisplayOptions()
        self.matrix = apply_display_options(matrix, self.options)

        self.SetSize((self.FromDIP(1100), self.FromDIP(680)))

        self._build_ui()
        self._apply_matrix(self.matrix)

    def _build_ui(self) -> None:
        container = wx.Panel(self)
        root = wx.BoxSizer(wx.HORIZONTAL)

        left = wx.BoxSizer(wx.VERTICAL)

        controls = wx.BoxSizer(wx.HORIZONTAL)
        self._rebuild_btn = wx.Button(container, label=_("Rebuild…"))
        self._rebuild_btn.Bind(wx.EVT_BUTTON, self._on_rebuild)
        controls.Add(self._rebuild_btn, 0, wx.RIGHT, self.FromDIP(8))

        self._export_btn = wx.Button(container, label=_("Export…"))
        self._export_btn.Bind(wx.EVT_BUTTON, self._on_export)
        controls.Add(self._export_btn, 0, wx.RIGHT, self.FromDIP(8))

        self._summary = wx.StaticText(container, label="")
        controls.Add(self._summary, 0, wx.ALIGN_CENTER_VERTICAL)
        left.Add(controls, 0, wx.ALL | wx.EXPAND, self.FromDIP(12))

        self.grid = gridlib.Grid(container)
        self.grid.CreateGrid(0, 0)
        self.grid.EnableEditing(False)
        self.grid.EnableDragGridSize(False)
        self.grid.SetSelectionMode(gridlib.Grid.SelectCells)
        self.grid.SetDefaultRowSize(self.FromDIP(28))
        self.grid.SetDefaultColSize(self.FromDIP(120))
        self.grid.SetRowLabelSize(self.FromDIP(240))
        self.grid.SetColLabelSize(self.FromDIP(90))
        self.grid.SetLabelFont(wx.Font(wx.FontInfo(10)))
        self.grid.Bind(gridlib.EVT_GRID_SELECT_CELL, self._on_cell_selected)
        self.grid.Bind(gridlib.EVT_GRID_LABEL_LEFT_CLICK, self._on_label_click)
        left.Add(self.grid, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, self.FromDIP(12))

        root.Add(left, 3, wx.EXPAND)

        self.details_panel = TraceMatrixDetailsPanel(container)
        root.Add(self.details_panel, 2, wx.TOP | wx.BOTTOM | wx.RIGHT | wx.EXPAND, self.FromDIP(12))

        container.SetSizer(root)
        frame_sizer = wx.BoxSizer(wx.VERTICAL)
        frame_sizer.Add(container, 1, wx.EXPAND)
        self.SetSizer(frame_sizer)

    def _apply_matrix(self, matrix: TraceMatrix) -> None:
        self.matrix = matrix
        table = TraceMatrixTable(matrix, compact_symbols=self.options.compact_symbols)
        self.grid.BeginBatch()
        try:
            self.grid.SetTable(table, True)
            self._configure_grid_dimensions(table)
        finally:
            self.grid.EndBatch()
        self.grid.ForceRefresh()
        self._summary.SetLabel(self._format_summary(matrix.summary))
        self.details_panel.show_message(_("Select a cell or header to view details."))

    def _on_rebuild(self, _event: wx.CommandEvent) -> None:
        config = self._prompt_config()
        if config is None:
            return
        try:
            matrix = self.controller.build_trace_matrix(config)
        except Exception as exc:  # pragma: no cover - wx reports the error
            wx.MessageBox(str(exc), _("Error"))
            return
        matrix = apply_display_options(matrix, self.options)
        if not matrix.rows or not matrix.columns:
            wx.MessageBox(_("The selected documents contain no requirements to display."), _("No data"))
            return
        self.config = config
        self._apply_matrix(matrix)

    def _prompt_config(self) -> TraceMatrixConfig | None:
        try:
            documents = self.controller.load_documents()
        except Exception as exc:  # pragma: no cover - defensive guard
            wx.MessageBox(str(exc), _("Error"))
            return None
        default_row = next(iter(self.config.rows.documents), None)
        default_column = next(iter(self.config.columns.documents), None)
        dialog = TraceMatrixConfigDialog(
            self,
            documents,
            default_rows=default_row,
            default_columns=default_column,
            direction=self.config.direction,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return None
            plan = dialog.get_plan()
        finally:
            dialog.Destroy()
        self.options = plan.options
        return plan.config

    def _on_export(self, _event: wx.CommandEvent) -> None:
        wildcard = "HTML (*.html)|*.html|CSV (*.csv)|*.csv|JSON (*.json)|*.json"
        dialog = wx.FileDialog(
            self,
            message=_("Export trace matrix"),
            wildcard=wildcard,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        )
        try:
            if dialog.ShowModal() != wx.ID_OK:
                return
            path = Path(dialog.GetPath())
        finally:
            dialog.Destroy()

        try:
            if path.suffix.lower() == ".html":
                _write_matrix_html(path, self.matrix, self.options)
            elif path.suffix.lower() == ".csv":
                _write_matrix_csv(path, self.matrix, self.options)
            elif path.suffix.lower() == ".json":
                _write_matrix_json(path, self.matrix, self.options)
            else:
                wx.MessageBox(_("Unsupported file extension"), _("Error"))
                return
        except Exception as exc:  # pragma: no cover - UI
            wx.MessageBox(str(exc), _("Error"))
            return

        wx.MessageBox(_("Trace matrix exported"), _("Done"))

    def _on_cell_selected(self, event: gridlib.GridEvent) -> None:  # pragma: no cover - GUI event
        self._show_cell_details(event.GetRow(), event.GetCol())
        event.Skip()

    def _on_label_click(self, event: gridlib.GridEvent) -> None:  # pragma: no cover - GUI event
        row = event.GetRow()
        col = event.GetCol()
        if row >= 0:
            self._show_row_details(row)
        elif col >= 0:
            self._show_column_details(col)
        event.Skip()

    def _show_cell_details(self, row: int, col: int) -> None:
        if row < 0 or col < 0 or row >= len(self.matrix.rows) or col >= len(self.matrix.columns):
            return
        row_entry = self.matrix.rows[row]
        column_entry = self.matrix.columns[col]
        cell = self.matrix.cells.get((row_entry.rid, column_entry.rid))
        state = _DetailsState(
            row_label=_build_axis_line(row_entry, self.options.selected_fields),
            column_label=_build_axis_line(column_entry, self.options.selected_fields),
            link_details=_describe_links(cell, self.matrix.direction),
        )
        self.details_panel.show_state(state)

    def _show_row_details(self, row: int) -> None:
        if row < 0 or row >= len(self.matrix.rows):
            return
        state = _DetailsState(
            row_label=_build_axis_line(self.matrix.rows[row], self.options.selected_fields),
            column_label="",
            link_details=_("Select a cell to view link information."),
        )
        self.details_panel.show_state(state)

    def _show_column_details(self, col: int) -> None:
        if col < 0 or col >= len(self.matrix.columns):
            return
        state = _DetailsState(
            row_label="",
            column_label=_build_axis_line(self.matrix.columns[col], self.options.selected_fields),
            link_details=_("Select a cell to view link information."),
        )
        self.details_panel.show_state(state)

    @staticmethod
    def _format_summary(summary) -> str:
        if summary.total_pairs == 0:
            return _("Requirements: {rows} × {columns}. No requirement combinations available").format(
                rows=summary.total_rows,
                columns=summary.total_columns,
            )
        return _("Requirements: {rows} × {columns}. Linked {linked} of {pairs} pairs ({coverage:.0%})").format(
            rows=summary.total_rows,
            columns=summary.total_columns,
            linked=summary.linked_pairs,
            pairs=summary.total_pairs,
            coverage=summary.pair_coverage,
        )

    def _configure_grid_dimensions(self, table: TraceMatrixTable) -> None:
        row_label_min = self.FromDIP(220)
        row_label_max = self.FromDIP(420)
        column_min = self.FromDIP(90)
        column_max = self.FromDIP(240)
        row_height_min = self.FromDIP(56)
        row_height_max = self.FromDIP(140)
        column_label_min = self.FromDIP(72)
        column_label_max = self.FromDIP(160)
        padding_x = self.FromDIP(16)
        padding_y = self.FromDIP(12)

        font = self.grid.GetLabelFont()
        dc = wx.MemoryDC()
        bitmap = wx.Bitmap(1, 1)
        dc.SelectObject(bitmap)
        if font.IsOk():
            dc.SetFont(font)

        try:
            row_label_width = row_label_min
            row_height = row_height_min
            for entry in table.rows:
                label = _format_label(entry)
                width, height = dc.GetMultiLineTextExtent(label)
                row_label_width = max(row_label_width, width + padding_x)
                row_height = max(row_height, height + padding_y)

            self.grid.SetRowLabelSize(int(min(row_label_width, row_label_max)))
            self.grid.SetDefaultRowSize(int(min(row_height, row_height_max)), True)

            column_label_height = column_label_min
            for col in range(table.GetNumberCols()):
                label = table.GetColLabelValue(col)
                width, height = dc.GetMultiLineTextExtent(label)
                self.grid.SetColSize(col, int(max(column_min, min(width + padding_x, column_max))))
                column_label_height = max(column_label_height, height + padding_y)

            self.grid.SetColLabelSize(int(min(column_label_height, column_label_max)))
        finally:
            dc.SelectObject(wx.NullBitmap)


def _describe_links(cell: TraceMatrixCell | None, direction: TraceDirection) -> str:
    if cell is None or not cell.links:
        return _("No links.")
    lines = [_("Total links: {count}").format(count=len(cell.links))]
    if direction == TraceDirection.CHILD_TO_PARENT:
        lines.append(_("Parents:"))
        lines.extend(f"• {link.target_rid}" for link in cell.links)
    else:
        lines.append(_("Children:"))
        lines.extend(f"• {link.source_rid}" for link in cell.links)
    if any(link.suspect for link in cell.links):
        lines.append(_("There are suspect links."))
    return "\n".join(lines)


def _write_matrix_csv(path: Path, matrix: TraceMatrix, options: TraceMatrixDisplayOptions) -> None:
    with path.open("w", encoding="utf-8", newline="") as out:
        writer = csv.writer(out)
        header = [field.upper() for field in options.selected_fields]
        header.extend(column.rid for column in matrix.columns)
        writer.writerow(header)
        for row in matrix.rows:
            cells: list[str] = []
            for column in matrix.columns:
                cell = matrix.cells.get((row.rid, column.rid))
                if not cell or not cell.links:
                    cells.append("")
                else:
                    cells.append("suspect" if cell.suspect else "linked")
            writer.writerow([_entry_field_value(row, field) for field in options.selected_fields] + cells)


def _write_matrix_html(path: Path, matrix: TraceMatrix, options: TraceMatrixDisplayOptions) -> None:
    with path.open("w", encoding="utf-8") as out:
        out.write("<!DOCTYPE html><html><head><meta charset='utf-8'>")
        out.write("<style>body{font-family:Arial,sans-serif;margin:24px}table{border-collapse:collapse}th,td{border:1px solid #ccc;padding:4px}thead th{position:sticky;top:0;background:#f2f2f2}.linked{background:#d1f2d9}.suspect{background:#fff3cd}</style>")
        out.write("</head><body><h1>Trace matrix</h1><table><thead><tr>")
        for field in options.selected_fields:
            out.write(f"<th>{html.escape(field.upper())}</th>")
        for column in matrix.columns:
            out.write(f"<th>{html.escape(column.rid)}</th>")
        out.write("</tr></thead><tbody>")
        for row in matrix.rows:
            out.write("<tr>")
            for field in options.selected_fields:
                out.write(f"<td>{html.escape(_entry_field_value(row, field))}</td>")
            for column in matrix.columns:
                cell = matrix.cells.get((row.rid, column.rid))
                if not cell or not cell.links:
                    out.write("<td>·</td>")
                else:
                    cls = "suspect" if cell.suspect else "linked"
                    marker = "!" if cell.suspect else "✓"
                    out.write(f"<td class='{cls}'>{marker}</td>")
            out.write("</tr>")
        out.write("</tbody></table></body></html>")


def _write_matrix_json(path: Path, matrix: TraceMatrix, options: TraceMatrixDisplayOptions) -> None:
    payload = {
        "direction": matrix.direction.value,
        "selected_fields": list(options.selected_fields),
        "rows": [
            {field: _entry_field_value(entry, field) for field in options.selected_fields}
            for entry in matrix.rows
        ],
        "columns": [column.rid for column in matrix.columns],
        "summary": {
            "total_rows": matrix.summary.total_rows,
            "total_columns": matrix.summary.total_columns,
            "linked_pairs": matrix.summary.linked_pairs,
            "total_pairs": matrix.summary.total_pairs,
            "pair_coverage": matrix.summary.pair_coverage,
            "orphan_rows": list(matrix.summary.orphan_rows),
            "orphan_columns": list(matrix.summary.orphan_columns),
        },
    }
    with path.open("w", encoding="utf-8") as out:
        json.dump(payload, out, ensure_ascii=False, indent=2, sort_keys=True)


__all__ = [
    "TraceMatrixConfigDialog",
    "TraceMatrixDisplayOptions",
    "TraceMatrixFrame",
    "TraceMatrixViewPlan",
    "apply_display_options",
]
