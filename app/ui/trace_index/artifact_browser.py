"""Artifact browser tab for the external evidence trace index."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import wx

from ...core.trace_index import TraceIndex
from ...i18n import _
from .artifact_viewer import TraceArtifactFrame

_KIND_CHOICES = ("all", "code", "test_case", "test_result")
_KIND_LABELS = {
    "all": "All Types",
    "code": "Code",
    "test_case": "Test Case",
    "test_result": "Test Result",
}


@dataclass(frozen=True)
class ArtifactRow:
    """Display metadata for one trace-index artifact row."""

    kind_id: str
    kind: str
    artifact: str
    requirements: str
    detail: str
    path: Path | None
    line: int | None


class TraceArtifactBrowserPanel(wx.Panel):
    """Browse code, test source and result artifacts from a TraceIndex."""

    def __init__(self, parent: wx.Window, *, project_root: Path) -> None:
        super().__init__(parent)
        self.project_root = Path(project_root)
        self._index: TraceIndex | None = None
        self._all_rows: list[ArtifactRow] = []
        self._rows: list[ArtifactRow] = []

        self.status_label = wx.StaticText(self, label=_("No trace index loaded."))
        self.type_filter = wx.Choice(
            self,
            choices=[_(_KIND_LABELS[kind]) for kind in _KIND_CHOICES],
        )
        self.type_filter.SetSelection(0)
        self.rid_filter = wx.TextCtrl(self)
        self.text_filter = wx.TextCtrl(self)
        self.group_by_rid = wx.CheckBox(self, label=_("Group by RID"))
        self.apply_filter_button = wx.Button(self, label=_("Apply Filter"))
        self.clear_filter_button = wx.Button(self, label=_("Clear Filter"))
        self.focus_rid_button = wx.Button(self, label=_("Focus RID"))
        self.focus_rid_button.Enable(False)
        self.open_button = wx.Button(self, label=_("Open Artifact"))
        self.open_button.Enable(False)
        self.artifacts = wx.ListCtrl(self, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.artifacts.InsertColumn(0, _("Type"), width=self.FromDIP(110))
        self.artifacts.InsertColumn(1, _("Artifact"), width=self.FromDIP(320))
        self.artifacts.InsertColumn(2, _("Requirements"), width=self.FromDIP(180))
        self.artifacts.InsertColumn(3, _("Detail"), width=self.FromDIP(360))

        top = wx.BoxSizer(wx.VERTICAL)
        top.Add(self._build_filter_bar(), 0, wx.EXPAND | wx.ALL, self.FromDIP(8))
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(self.open_button, 0, wx.RIGHT, self.FromDIP(8))
        actions.Add(self.status_label, 1, wx.ALIGN_CENTER_VERTICAL)
        top.Add(actions, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(8))
        top.Add(
            self.artifacts,
            1,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            self.FromDIP(8),
        )
        self.SetSizer(top)

        self.open_button.Bind(wx.EVT_BUTTON, self.on_open_artifact)
        self.apply_filter_button.Bind(wx.EVT_BUTTON, self.on_apply_filter)
        self.clear_filter_button.Bind(wx.EVT_BUTTON, self.on_clear_filter)
        self.focus_rid_button.Bind(wx.EVT_BUTTON, self.on_focus_rid)
        self.group_by_rid.Bind(wx.EVT_CHECKBOX, self.on_grouping_changed)
        self.artifacts.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_selection_changed)
        self.artifacts.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_selection_changed)
        self.artifacts.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_artifact_activated)

    def _build_filter_bar(self) -> wx.StaticBoxSizer:
        filters = wx.StaticBoxSizer(wx.VERTICAL, self, _("Artifact Filters"))
        grid = wx.FlexGridSizer(
            rows=0,
            cols=2,
            vgap=self.FromDIP(4),
            hgap=self.FromDIP(8),
        )
        grid.AddGrowableCol(1, 1)
        self._add_filter_row(grid, _("Type"), self.type_filter)
        self._add_filter_row(grid, _("RID contains"), self.rid_filter)
        self._add_filter_row(grid, _("Text contains"), self.text_filter)
        self._add_filter_row(grid, _("Grouping"), self.group_by_rid)
        filters.Add(grid, 0, wx.EXPAND | wx.ALL, self.FromDIP(8))
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(self.apply_filter_button, 0, wx.RIGHT, self.FromDIP(8))
        actions.Add(self.clear_filter_button, 0, wx.RIGHT, self.FromDIP(8))
        actions.Add(self.focus_rid_button, 0)
        filters.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(8))
        return filters

    @staticmethod
    def _add_filter_row(
        grid: wx.FlexGridSizer,
        label: str,
        control: wx.Control,
    ) -> None:
        grid.Add(
            wx.StaticText(control.GetParent(), label=label),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        grid.Add(control, 1, wx.EXPAND)

    def set_index(self, index: TraceIndex | None) -> None:
        """Populate the browser from ``index`` or clear it when unavailable."""
        self._index = index
        if index is None:
            self._all_rows.clear()
            self._rows.clear()
            self.artifacts.DeleteAllItems()
            self.status_label.SetLabel(_("No trace index loaded."))
            self._sync_open_button()
            return
        self._rebuild_rows()

    def on_apply_filter(self, _event: wx.Event) -> None:
        """Apply browser filters to current artifact rows."""
        self._apply_filters()

    def on_clear_filter(self, _event: wx.Event) -> None:
        """Clear browser filters and show all current artifact rows."""
        self.type_filter.SetSelection(0)
        self.rid_filter.SetValue("")
        self.text_filter.SetValue("")
        self._apply_filters()

    def on_grouping_changed(self, _event: wx.CommandEvent) -> None:
        """Rebuild browser rows when requirement grouping changes."""
        self._rebuild_rows()

    def on_focus_rid(self, _event: wx.Event) -> None:
        """Filter the browser to the first RID from the selected row."""
        selected = self.artifacts.GetFirstSelected()
        if selected == -1 or selected >= len(self._rows):
            return
        rid = _first_rid(self._rows[selected].requirements)
        if rid:
            self.focus_rid(rid)

    def focus_rid(self, rid: str) -> None:
        """Filter browser rows to artifacts related to ``rid``."""
        self.rid_filter.SetValue(rid)
        self._apply_filters()

    def on_selection_changed(self, _event: wx.ListEvent) -> None:
        """Keep the open button in sync with current selection."""
        self._sync_open_button()

    def on_artifact_activated(self, event: wx.ListEvent) -> None:
        """Open an activated artifact row."""
        self._open_artifact(event.GetIndex())

    def on_open_artifact(self, _event: wx.Event) -> None:
        """Open the selected artifact row."""
        selected = self.artifacts.GetFirstSelected()
        if selected != -1:
            self._open_artifact(selected)

    def _rebuild_rows(self) -> None:
        self._all_rows.clear()
        if self._index is not None:
            self._all_rows.extend(self._build_rows(self._index))
        self._apply_filters()

    def _apply_filters(self) -> None:
        selected_kind = _KIND_CHOICES[max(self.type_filter.GetSelection(), 0)]
        rid_filter = self.rid_filter.GetValue().strip().casefold()
        text_filter = self.text_filter.GetValue().strip().casefold()
        self._rows = [
            row
            for row in self._all_rows
            if self._row_matches(row, selected_kind, rid_filter, text_filter)
        ]
        self._render_rows()

    def _row_matches(
        self,
        row: ArtifactRow,
        selected_kind: str,
        rid_filter: str,
        text_filter: str,
    ) -> bool:
        if selected_kind != "all" and row.kind_id != selected_kind:
            return False
        if rid_filter and rid_filter not in row.requirements.casefold():
            return False
        haystack = f"{row.artifact}\n{row.requirements}\n{row.detail}".casefold()
        return not text_filter or text_filter in haystack

    def _render_rows(self) -> None:
        self.artifacts.DeleteAllItems()
        for row in self._rows:
            item = self.artifacts.GetItemCount()
            self.artifacts.InsertItem(item, row.kind)
            self.artifacts.SetItem(item, 1, row.artifact)
            self.artifacts.SetItem(item, 2, row.requirements)
            self.artifacts.SetItem(item, 3, row.detail)
        self.status_label.SetLabel(
            _("Artifacts: {shown} of {total}").format(
                shown=len(self._rows),
                total=len(self._all_rows),
            )
        )
        self._sync_open_button()

    def _build_rows(self, index: TraceIndex) -> list[ArtifactRow]:
        rows: list[ArtifactRow] = []
        grouped = self.group_by_rid.GetValue()
        for location in index.code_locations:
            self._append_rows(
                rows,
                kind_id="code",
                kind=_("Code"),
                artifact=self._artifact_label(location.path, location.line_start),
                covers=(location.rid,),
                detail=location.symbol or location.marker_text,
                path=self._resolve_path(location.path),
                line=location.line_start,
                grouped=grouped,
            )
        for test_case in index.test_cases:
            self._append_rows(
                rows,
                kind_id="test_case",
                kind=_("Test Case"),
                artifact=self._artifact_label(test_case.path, test_case.line_start),
                covers=test_case.covers,
                detail=test_case.test_id,
                path=self._resolve_path(test_case.path),
                line=test_case.line_start,
                grouped=grouped,
            )
        for result in index.test_results:
            self._append_rows(
                rows,
                kind_id="test_result",
                kind=_("Test Result"),
                artifact=self._artifact_label(result.result_file, result.line_start),
                covers=result.covers,
                detail=f"{result.test_id}: {result.normalized_status}",
                path=self._resolve_path(result.result_file),
                line=result.line_start,
                grouped=grouped,
            )
        return rows

    def _append_rows(
        self,
        rows: list[ArtifactRow],
        *,
        kind_id: str,
        kind: str,
        artifact: str,
        covers: tuple[str, ...],
        detail: str,
        path: Path | None,
        line: int | None,
        grouped: bool,
    ) -> None:
        requirements = covers if grouped else (", ".join(covers),)
        for requirement in requirements:
            rows.append(
                ArtifactRow(
                    kind_id=kind_id,
                    kind=kind,
                    artifact=artifact,
                    requirements=requirement,
                    detail=detail,
                    path=path,
                    line=line,
                )
            )

    def _artifact_label(self, path: str, line: int | None) -> str:
        suffix = f":{line}" if line is not None else ""
        return f"{path}{suffix}"

    def _resolve_path(self, path: str) -> Path | None:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.project_root / candidate
        try:
            resolved = candidate.resolve(strict=False)
            resolved.relative_to(self.project_root.resolve(strict=False))
        except (OSError, ValueError):
            return None
        return resolved

    def _open_artifact(self, index: int) -> None:
        if index < 0 or index >= len(self._rows):
            return
        row = self._rows[index]
        if row.path is None or not row.path.is_file():
            wx.MessageBox(
                _("Artifact file does not exist: {path}").format(path=row.artifact),
                _("No Location"),
                parent=self,
            )
            return
        frame = TraceArtifactFrame(
            self,
            path=row.path,
            project_root=self.project_root,
            line=row.line,
        )
        frame.Show()

    def _sync_open_button(self) -> None:
        selected = self.artifacts.GetFirstSelected()
        enabled = (
            selected != -1
            and selected < len(self._rows)
            and self._rows[selected].path is not None
        )
        self.open_button.Enable(enabled)
        self.focus_rid_button.Enable(
            selected != -1
            and selected < len(self._rows)
            and bool(_first_rid(self._rows[selected].requirements))
        )


def _first_rid(requirements: str) -> str:
    return requirements.split(",", 1)[0].strip()
