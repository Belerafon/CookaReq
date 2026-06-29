"""Artifact trace matrix tab for the external evidence trace index."""
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import wx

from ...core.trace_index import (
    TraceArtifactMatrix,
    TraceIndex,
    build_artifact_trace_matrix,
    render_artifact_matrix_csv,
    render_artifact_matrix_html,
)
from ...core.trace_index.matrix import TraceArtifactMatrixCell
from ...i18n import _

_CELL_LABELS = {
    "code": "Code",
    "test_case": "Test Case",
    "test_result": "Test Result",
}


class TraceArtifactMatrixPanel(wx.Panel):
    """Display a requirement x external artifact matrix for a TraceIndex."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        project_root: Path,
        on_requirement_focus: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root)
        self._index: TraceIndex | None = None
        self._column_ids: list[str] = []
        self._matrix: TraceArtifactMatrix | None = None
        self._requirement_rids: list[str] = []
        self._on_requirement_focus = on_requirement_focus

        self.status_label = wx.StaticText(self, label=_("No trace index loaded."))
        self.export_json_button = wx.Button(self, label=_("Export JSON"))
        self.export_csv_button = wx.Button(self, label=_("Export CSV"))
        self.export_html_button = wx.Button(self, label=_("Export HTML"))
        self.focus_browser_button = wx.Button(self, label=_("Focus Browser"))
        self.export_json_button.Enable(False)
        self.export_csv_button.Enable(False)
        self.export_html_button.Enable(False)
        self.focus_browser_button.Enable(False)
        self.matrix = wx.ListCtrl(self, style=wx.LC_REPORT | wx.BORDER_SUNKEN)

        top = wx.BoxSizer(wx.VERTICAL)
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(self.export_json_button, 0, wx.RIGHT, self.FromDIP(8))
        actions.Add(self.export_csv_button, 0, wx.RIGHT, self.FromDIP(8))
        actions.Add(self.export_html_button, 0, wx.RIGHT, self.FromDIP(8))
        actions.Add(self.focus_browser_button, 0, wx.RIGHT, self.FromDIP(8))
        actions.Add(self.status_label, 1, wx.ALIGN_CENTER_VERTICAL)
        top.Add(actions, 0, wx.EXPAND | wx.ALL, self.FromDIP(8))
        top.Add(
            self.matrix,
            1,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            self.FromDIP(8),
        )
        self.SetSizer(top)
        self.export_json_button.Bind(wx.EVT_BUTTON, self.on_export_json)
        self.export_csv_button.Bind(wx.EVT_BUTTON, self.on_export_csv)
        self.export_html_button.Bind(wx.EVT_BUTTON, self.on_export_html)
        self.focus_browser_button.Bind(wx.EVT_BUTTON, self.on_focus_browser)
        self.matrix.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_selection_changed)
        self.matrix.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_selection_changed)
        self._reset_columns()

    def set_index(self, index: TraceIndex | None) -> None:
        """Render matrix rows for ``index`` or clear the table when unavailable."""
        self._index = index
        self._matrix = None
        self._requirement_rids.clear()
        self.matrix.DeleteAllItems()
        self._reset_columns()
        if index is None:
            self.status_label.SetLabel(_("No trace index loaded."))
            self._sync_export_buttons()
            return
        matrix = build_artifact_trace_matrix(index)
        self._matrix = matrix
        self._render_matrix(matrix)
        self._sync_export_buttons()

    def on_export_json(self, _event: wx.Event) -> None:
        """Export the current artifact matrix to a JSON file."""
        self._export_with_dialog(
            format_id="json",
            wildcard=_("JSON files (*.json)|*.json"),
            default_file="trace_artifact_matrix.json",
        )

    def on_export_csv(self, _event: wx.Event) -> None:
        """Export the current artifact matrix to a CSV file."""
        self._export_with_dialog(
            format_id="csv",
            wildcard=_("CSV files (*.csv)|*.csv"),
            default_file="trace_artifact_matrix.csv",
        )

    def on_export_html(self, _event: wx.Event) -> None:
        """Export the current artifact matrix to an HTML file."""
        self._export_with_dialog(
            format_id="html",
            wildcard=_("HTML files (*.html)|*.html"),
            default_file="trace_artifact_matrix.html",
        )

    def on_focus_browser(self, _event: wx.Event) -> None:
        """Ask the Artifact Browser to focus the selected requirement RID."""
        rid = self.selected_requirement_rid()
        if rid and self._on_requirement_focus is not None:
            self._on_requirement_focus(rid)

    def on_selection_changed(self, _event: wx.ListEvent) -> None:
        """Keep RID focus action in sync with current matrix selection."""
        self._sync_focus_button()

    def selected_requirement_rid(self) -> str | None:
        """Return the RID selected in the matrix, if any."""
        selected = self.matrix.GetFirstSelected()
        if selected == -1 or selected >= len(self._requirement_rids):
            return None
        return self._requirement_rids[selected]

    def export_matrix(self, path: Path, *, format_id: str) -> None:
        """Write the current artifact matrix to ``path`` in the selected format."""
        if self._matrix is None:
            raise ValueError(_("No trace index loaded."))
        if format_id == "json":
            payload = (
                json.dumps(self._matrix.to_dict(), ensure_ascii=False, indent=2)
                + "\n"
            )
        elif format_id == "csv":
            payload = render_artifact_matrix_csv(self._matrix)
        elif format_id == "html":
            payload = render_artifact_matrix_html(self._matrix)
        else:
            raise ValueError(
                _("Unsupported export format: {format}").format(format=format_id)
            )
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload, encoding="utf-8")

    def _export_with_dialog(
        self,
        *,
        format_id: str,
        wildcard: str,
        default_file: str,
    ) -> None:
        if self._matrix is None:
            wx.MessageBox(_("No trace index loaded."), _("Export Matrix"), parent=self)
            return
        with wx.FileDialog(
            self,
            message=_("Export Matrix"),
            defaultFile=default_file,
            wildcard=wildcard,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            try:
                self.export_matrix(Path(dialog.GetPath()), format_id=format_id)
            except OSError as exc:
                wx.MessageBox(str(exc), _("Error"), parent=self)

    def _reset_columns(self) -> None:
        self.matrix.DeleteAllColumns()
        self.matrix.InsertColumn(0, _("Requirement"), width=self.FromDIP(100))
        self.matrix.InsertColumn(1, _("Title"), width=self.FromDIP(220))
        self._column_ids.clear()

    def _render_matrix(self, matrix: TraceArtifactMatrix) -> None:
        for column in matrix.columns:
            self._column_ids.append(column.column_id)
            header = f"{_(_CELL_LABELS.get(column.kind, column.kind))}: {column.label}"
            self.matrix.InsertColumn(
                self.matrix.GetColumnCount(),
                header,
                width=self.FromDIP(180),
            )
        column_positions = {
            column_id: offset + 2 for offset, column_id in enumerate(self._column_ids)
        }
        cells_by_rid: dict[str, dict[str, TraceArtifactMatrixCell]] = {}
        for cell in matrix.cells:
            cells_by_rid.setdefault(cell.rid, {})[cell.column_id] = cell
        for requirement in matrix.requirements:
            row = self.matrix.GetItemCount()
            self._requirement_rids.append(requirement.rid)
            self.matrix.InsertItem(row, requirement.rid)
            self.matrix.SetItem(row, 1, requirement.title)
            for column_id, cell in cells_by_rid.get(requirement.rid, {}).items():
                self.matrix.SetItem(row, column_positions[column_id], _cell_text(cell))
        self.status_label.SetLabel(
            _("Matrix: {requirements} requirements x {artifacts} artifacts").format(
                requirements=len(matrix.requirements),
                artifacts=len(matrix.columns),
            )
        )

    def _sync_export_buttons(self) -> None:
        enabled = self._matrix is not None
        self.export_json_button.Enable(enabled)
        self.export_csv_button.Enable(enabled)
        self.export_html_button.Enable(enabled)
        self._sync_focus_button()

    def _sync_focus_button(self) -> None:
        self.focus_browser_button.Enable(
            self._matrix is not None
            and self._on_requirement_focus is not None
            and self.selected_requirement_rid() is not None
        )


def _cell_text(cell: TraceArtifactMatrixCell) -> str:
    if cell.marker == "test_result" and cell.status:
        return cell.status
    return _(_CELL_LABELS.get(cell.marker, cell.marker))
