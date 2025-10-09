"""Graphical traceability matrix viewer."""
from __future__ import annotations

from dataclasses import dataclass
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


def _format_document_label(doc: Document) -> str:
    title = doc.title.strip()
    if not title:
        return doc.prefix
    if title == doc.prefix:
        return title
    return f"{doc.prefix} — {title}"


class TraceMatrixConfigDialog(wx.Dialog):
    """Collect row and column document selections from the user."""
    def __init__(
        self,
        parent: wx.Window | None,
        documents: Mapping[str, Document],
        *,
        default_rows: str | None = None,
        default_columns: str | None = None,
        direction: TraceDirection = TraceDirection.CHILD_TO_PARENT,
    ) -> None:
        """Prepare dialog controls for selecting trace matrix axes."""
        if not documents:
            raise ValueError("documents cannot be empty")

        super().__init__(parent, title=_("Trace Matrix Configuration"))
        self.SetEscapeId(wx.ID_CANCEL)

        self._documents = documents
        self._direction = direction
        self._prefixes = sorted(documents)

        choices = [_format_document_label(documents[prefix]) for prefix in self._prefixes]

        main_sizer = wx.BoxSizer(wx.VERTICAL)
        form = wx.FlexGridSizer(rows=2, cols=2, hgap=8, vgap=8)

        form.AddGrowableCol(1, proportion=1)

        form.Add(wx.StaticText(self, label=_("Rows document")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._rows_choice = wx.Choice(self, choices=choices)
        form.Add(self._rows_choice, 1, wx.EXPAND)

        form.Add(wx.StaticText(self, label=_("Columns document")), 0, wx.ALIGN_CENTER_VERTICAL)
        self._columns_choice = wx.Choice(self, choices=choices)
        form.Add(self._columns_choice, 1, wx.EXPAND)

        padding = self.FromDIP(12)
        main_sizer.Add(form, 0, wx.ALL | wx.EXPAND, padding)

        button_sizer = self.CreateSeparatedButtonSizer(wx.OK | wx.CANCEL)
        if button_sizer is not None:
            main_sizer.Add(button_sizer, 0, wx.ALL | wx.EXPAND, padding)

        self.SetSizer(main_sizer)
        self.Fit()
        self.CentreOnParent()

        self._select_default(self._rows_choice, default_rows)
        self._select_default(self._columns_choice, default_columns)
        if self._columns_choice.GetSelection() == wx.NOT_FOUND:
            # fall back to the first document different from rows
            row_index = self._rows_choice.GetSelection()
            fallback = 0
            if row_index != wx.NOT_FOUND and len(self._prefixes) > 1:
                fallback = (row_index + 1) % len(self._prefixes)
            self._columns_choice.SetSelection(fallback)

        ok_button = self.FindWindowById(wx.ID_OK)
        if isinstance(ok_button, wx.Button):
            ok_button.SetDefault()

    # ------------------------------------------------------------------
    def _select_default(self, choice: wx.Choice, prefix: str | None) -> None:
        if prefix and prefix in self._prefixes:
            choice.SetSelection(self._prefixes.index(prefix))
        elif self._prefixes:
            choice.SetSelection(0)

    def get_config(self) -> TraceMatrixConfig:
        """Return :class:`TraceMatrixConfig` built from dialog selections."""
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


class TraceMatrixTable(gridlib.GridTableBase):
    """Virtual table exposing :class:`TraceMatrix` data to :class:`wx.grid.Grid`."""
    _LINK_SYMBOL = "\u25CF"

    def __init__(self, matrix: TraceMatrix) -> None:
        """Initialise table with the provided :class:`TraceMatrix`."""
        super().__init__()
        self.update_matrix(matrix)
        self._link_colour = wx.Colour(102, 187, 106)
        self._link_text_colour = wx.Colour(32, 32, 32)

    # lifecycle --------------------------------------------------------
    def update_matrix(self, matrix: TraceMatrix) -> None:
        self.matrix = matrix
        self.rows = matrix.rows
        self.columns = matrix.columns
        self.cells = matrix.cells

    # GridTableBase API ------------------------------------------------
    def GetNumberRows(self) -> int:  # noqa: N802 - wx naming
        return len(self.rows)

    def GetNumberCols(self) -> int:  # noqa: N802 - wx naming
        return len(self.columns)

    def IsEmptyCell(self, row: int, col: int) -> bool:  # noqa: N802 - wx naming
        return not self._get_cell(row, col)

    def GetValue(self, row: int, col: int) -> str:  # noqa: N802 - wx naming
        cell = self._get_cell(row, col)
        if not cell:
            return ""
        count = len(cell.links)
        return self._LINK_SYMBOL if count == 1 else str(count)

    def GetAttr(  # noqa: N802 - wx naming
        self,
        row: int,
        col: int,
        kind: int,
    ) -> gridlib.GridCellAttr | None:
        cell = self._get_cell(row, col)
        if not cell:
            attr = gridlib.GridCellAttr()
            attr.SetReadOnly(True)
            attr.IncRef()
            return attr
        attr = gridlib.GridCellAttr()
        attr.SetReadOnly(True)
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

    # helpers ---------------------------------------------------------
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
    """Aggregated view of the currently selected matrix entries."""
    row_label: str = ""
    column_label: str = ""
    link_details: str = ""


class TraceMatrixDetailsPanel(wx.Panel):
    """Display contextual information about the current selection."""
    def __init__(self, parent: wx.Window) -> None:
        """Create details panel hosting summary widgets."""
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

    # ------------------------------------------------------------------
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
    ) -> None:
        """Construct the frame and render the initial matrix state."""
        super().__init__(parent, title=_("Trace Matrix"))
        self.controller = controller
        self.config = config
        self.matrix = matrix

        self.SetSize((self.FromDIP(1100), self.FromDIP(680)))

        self._build_ui()
        self._apply_matrix(matrix)

    # UI construction -------------------------------------------------
    def _build_ui(self) -> None:
        container = wx.Panel(self)
        root = wx.BoxSizer(wx.HORIZONTAL)

        left = wx.BoxSizer(wx.VERTICAL)

        controls = wx.BoxSizer(wx.HORIZONTAL)
        self._rebuild_btn = wx.Button(container, label=_("Rebuild…"))
        self._rebuild_btn.Bind(wx.EVT_BUTTON, self._on_rebuild)
        controls.Add(self._rebuild_btn, 0, wx.RIGHT, self.FromDIP(8))

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

    # data binding ----------------------------------------------------
    def _apply_matrix(self, matrix: TraceMatrix) -> None:
        self.matrix = matrix
        table = TraceMatrixTable(matrix)
        self.grid.BeginBatch()
        try:
            self.grid.SetTable(table, True)
            self._configure_grid_dimensions(table)
        finally:
            self.grid.EndBatch()
        self.grid.ForceRefresh()
        self._summary.SetLabel(self._format_summary(matrix.summary))
        self.details_panel.show_message(_("Select a cell or header to view details."))

    # event handlers --------------------------------------------------
    def _on_rebuild(self, _event: wx.CommandEvent) -> None:
        config = self._prompt_config()
        if config is None:
            return
        try:
            matrix = self.controller.build_trace_matrix(config)
        except Exception as exc:  # pragma: no cover - wx reports the error
            wx.MessageBox(str(exc), _("Error"))
            return
        if not matrix.rows or not matrix.columns:
            wx.MessageBox(
                _("The selected documents contain no requirements to display."),
                _("No data"),
            )
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
            return dialog.get_config()
        finally:
            dialog.Destroy()

    def _on_cell_selected(self, event: gridlib.GridEvent) -> None:  # pragma: no cover - GUI event
        row = event.GetRow()
        col = event.GetCol()
        self._show_cell_details(row, col)
        event.Skip()

    def _on_label_click(self, event: gridlib.GridEvent) -> None:  # pragma: no cover - GUI event
        row = event.GetRow()
        col = event.GetCol()
        if row >= 0:
            self._show_row_details(row)
        elif col >= 0:
            self._show_column_details(col)
        event.Skip()

    # detail helpers --------------------------------------------------
    def _show_cell_details(self, row: int, col: int) -> None:
        if not self.matrix:
            return
        if row < 0 or col < 0:
            return
        if row >= len(self.matrix.rows) or col >= len(self.matrix.columns):
            return
        row_entry = self.matrix.rows[row]
        column_entry = self.matrix.columns[col]
        key = (row_entry.rid, column_entry.rid)
        cell = self.matrix.cells.get(key)
        state = _DetailsState(
            row_label=_describe_requirement(row_entry),
            column_label=_describe_requirement(column_entry),
            link_details=_describe_links(cell, self.matrix.direction),
        )
        self.details_panel.show_state(state)

    def _show_row_details(self, row: int) -> None:
        if not self.matrix:
            return
        if row < 0 or row >= len(self.matrix.rows):
            return
        entry = self.matrix.rows[row]
        state = _DetailsState(
            row_label=_describe_requirement(entry),
            column_label="",
            link_details=_("Select a cell to view link information."),
        )
        self.details_panel.show_state(state)

    def _show_column_details(self, col: int) -> None:
        if not self.matrix:
            return
        if col < 0 or col >= len(self.matrix.columns):
            return
        entry = self.matrix.columns[col]
        state = _DetailsState(
            row_label="",
            column_label=_describe_requirement(entry),
            link_details=_("Select a cell to view link information."),
        )
        self.details_panel.show_state(state)

    # summary ---------------------------------------------------------
    @staticmethod
    def _format_summary(summary) -> str:
        if summary.total_pairs == 0:
            return _(
                "Requirements: {rows} × {columns}. No requirement combinations available"
            ).format(rows=summary.total_rows, columns=summary.total_columns)
        return _(
            "Requirements: {rows} × {columns}. Linked {linked} of {pairs} pairs ({coverage:.0%})"
        ).format(
            rows=summary.total_rows,
            columns=summary.total_columns,
            linked=summary.linked_pairs,
            pairs=summary.total_pairs,
            coverage=summary.pair_coverage,
        )

    # sizing ----------------------------------------------------------
    def _configure_grid_dimensions(self, table: TraceMatrixTable) -> None:
        """Adapt grid label and cell sizes to the current dataset."""
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

            row_label_width = min(row_label_width, row_label_max)
            row_height = min(row_height, row_height_max)
            self.grid.SetRowLabelSize(int(row_label_width))
            self.grid.SetDefaultRowSize(int(row_height), True)

            column_label_height = column_label_min
            for col in range(table.GetNumberCols()):
                label = table.GetColLabelValue(col)
                width, height = dc.GetMultiLineTextExtent(label)
                best_width = max(column_min, min(width + padding_x, column_max))
                self.grid.SetColSize(col, int(best_width))
                column_label_height = max(column_label_height, height + padding_y)

            column_label_height = min(column_label_height, column_label_max)
            self.grid.SetColLabelSize(int(column_label_height))
        finally:
            dc.SelectObject(wx.NullBitmap)


def _describe_requirement(entry) -> str:
    req = entry.requirement
    doc = entry.document
    status = getattr(req.status, "value", str(req.status))
    req_type = getattr(req.type, "value", str(req.type))
    lines = [
        _("RID: {rid}").format(rid=req.rid),
        req.title or _("(untitled)"),
        _("Document: {doc}").format(doc=_format_document_label(doc)),
        _("Type: {type}").format(type=req_type),
        _("Status: {status}").format(status=status),
    ]
    return "\n".join(lines)


def _describe_links(cell: TraceMatrixCell | None, direction: TraceDirection) -> str:
    if cell is None or not cell.links:
        return _("No links.")
    lines = [_("Total links: {count}").format(count=len(cell.links))]
    if direction == TraceDirection.CHILD_TO_PARENT:
        header = _("Parents:")
        items = [link.target_rid for link in cell.links]
    else:
        header = _("Children:")
        items = [link.source_rid for link in cell.links]
    lines.append(header)
    lines.extend(f"• {rid}" for rid in items)
    if any(link.suspect for link in cell.links):
        lines.append(_("There are suspect links."))
    return "\n".join(lines)


__all__ = [
    "TraceMatrixConfigDialog",
    "TraceMatrixFrame",
]
