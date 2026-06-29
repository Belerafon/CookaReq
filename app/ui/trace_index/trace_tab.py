"""Trace-index GUI panel for external evidence artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from typing import Callable

import wx

from ...core.trace_index import (
    TraceIndex,
    TraceIndexConfig,
    TraceIssue,
    build_artifact_trace_matrix,
    build_trace_index,
    cache_path,
    read_trace_index_cache_for_config,
    render_trace_index_report_html,
    write_trace_index_cache,
)
from ...i18n import _
from .artifact_browser import TraceArtifactBrowserPanel
from .artifact_viewer import TraceArtifactFrame
from .matrix_panel import TraceArtifactMatrixPanel


@dataclass(frozen=True)
class TraceIndexRefreshResult:
    """Outcome displayed by the trace-index panel after refresh."""

    index: TraceIndex
    cache_file: Path


@dataclass(frozen=True)
class TraceIssueRow:
    """Issue plus resolved display/open-location metadata for the GUI."""

    issue: TraceIssue
    location_text: str
    artifact_path: Path | None
    line: int | None


class TraceIndexPanel(wx.Panel):
    """Panel showing cache state, summary and diagnostics for trace-index."""

    def __init__(
        self,
        parent: wx.Window,
        *,
        req_root: Path,
        project_root: Path | None = None,
        refresh_runner: Callable[[TraceIndexConfig], TraceIndexRefreshResult] | None = None,
        on_index_changed: Callable[[TraceIndex | None], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.req_root = Path(req_root)
        self.project_root = (
            Path(project_root) if project_root is not None else self.req_root.parent
        )
        self.config = TraceIndexConfig.from_conventions(
            self.req_root,
            project_root=self.project_root,
        )
        self._refresh_runner = refresh_runner or self._refresh_index
        self._on_index_changed = on_index_changed
        self._worker: Thread | None = None
        self._refreshing = False
        self._index: TraceIndex | None = None
        self._issue_rows: list[TraceIssueRow] = []

        self.module_filter_text = wx.TextCtrl(
            self,
            value=self.config.module_filter or "",
        )
        self.source_globs_text = wx.TextCtrl(
            self,
            value=_format_globs(self.config.source_globs),
        )
        self.test_globs_text = wx.TextCtrl(
            self,
            value=_format_globs(self.config.test_globs),
        )
        self.result_globs_text = wx.TextCtrl(
            self,
            value=_format_globs(self.config.result_globs),
        )
        self.exclude_globs_text = wx.TextCtrl(
            self,
            value=_format_globs(self.config.exclude_globs),
        )

        self.refresh_button = wx.Button(self, label=_("Refresh Trace Index"))
        self.open_location_button = wx.Button(self, label=_("Open Location"))
        self.open_location_button.Enable(False)
        self.export_report_button = wx.Button(self, label=_("Export Report"))
        self.export_report_button.Enable(False)
        self.status_label = wx.StaticText(
            self,
            label=_("Trace index cache has not been checked yet."),
        )
        self.summary_label = wx.StaticText(self, label="")
        self.cache_label = wx.StaticText(self, label="")
        self.issues = wx.ListCtrl(self, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        self.issues.InsertColumn(0, _("Severity"), width=self.FromDIP(90))
        self.issues.InsertColumn(1, _("Code"), width=self.FromDIP(170))
        self.issues.InsertColumn(2, _("Location"), width=self.FromDIP(260))
        self.issues.InsertColumn(3, _("Message"), width=self.FromDIP(480))

        top = wx.BoxSizer(wx.VERTICAL)
        top.Add(self._build_scan_settings(), 0, wx.EXPAND | wx.ALL, self.FromDIP(8))
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(self.refresh_button, 0, wx.RIGHT, self.FromDIP(8))
        actions.Add(self.open_location_button, 0, wx.RIGHT, self.FromDIP(8))
        actions.Add(self.export_report_button, 0, wx.RIGHT, self.FromDIP(8))
        actions.Add(self.status_label, 1, wx.ALIGN_CENTER_VERTICAL)
        top.Add(actions, 0, wx.EXPAND | wx.ALL, self.FromDIP(8))
        top.Add(self.summary_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(8))
        top.Add(self.cache_label, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(8))
        top.Add(
            self.issues,
            1,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            self.FromDIP(8),
        )
        self.SetSizer(top)

        self.refresh_button.Bind(wx.EVT_BUTTON, self.on_refresh)
        self.open_location_button.Bind(wx.EVT_BUTTON, self.on_open_location)
        self.export_report_button.Bind(wx.EVT_BUTTON, self.on_export_report)
        self.issues.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_issue_selected)
        self.issues.Bind(wx.EVT_LIST_ITEM_DESELECTED, self.on_issue_selected)
        self.issues.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_issue_activated)
        self._show_cache_state()

    def _build_scan_settings(self) -> wx.StaticBoxSizer:
        settings = wx.StaticBoxSizer(wx.VERTICAL, self, _("Scan Settings"))
        grid = wx.FlexGridSizer(
            rows=0,
            cols=2,
            vgap=self.FromDIP(4),
            hgap=self.FromDIP(8),
        )
        grid.AddGrowableCol(1, 1)
        self._add_settings_row(grid, _("Module"), self.module_filter_text)
        self._add_settings_row(grid, _("Source globs"), self.source_globs_text)
        self._add_settings_row(grid, _("Test source globs"), self.test_globs_text)
        self._add_settings_row(grid, _("Result globs"), self.result_globs_text)
        self._add_settings_row(grid, _("Exclude globs"), self.exclude_globs_text)
        settings.Add(grid, 0, wx.EXPAND | wx.ALL, self.FromDIP(8))
        hint = wx.StaticText(
            self,
            label=_("Separate multiple glob patterns with semicolons."),
        )
        settings.Add(hint, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, self.FromDIP(8))
        return settings

    @staticmethod
    def _add_settings_row(
        grid: wx.FlexGridSizer,
        label: str,
        control: wx.TextCtrl,
    ) -> None:
        grid.Add(
            wx.StaticText(control.GetParent(), label=label),
            0,
            wx.ALIGN_CENTER_VERTICAL,
        )
        grid.Add(control, 1, wx.EXPAND)

    def _config_from_controls(self) -> TraceIndexConfig:
        module = self.module_filter_text.GetValue().strip() or None
        return TraceIndexConfig.from_conventions(
            self.req_root,
            project_root=self.project_root,
            source_globs=_parse_globs(self.source_globs_text.GetValue()),
            test_globs=_parse_globs(self.test_globs_text.GetValue()),
            result_globs=_parse_globs(self.result_globs_text.GetValue()),
            exclude_globs=_parse_globs(self.exclude_globs_text.GetValue()),
            module_filter=module,
        )

    def on_refresh(self, _event: wx.Event) -> None:
        """Start a background refresh and write the generated cache."""
        self.refresh()

    def on_issue_selected(self, _event: wx.ListEvent) -> None:
        """Enable location opening only for diagnostics backed by files."""
        self._sync_open_location_button()

    def on_issue_activated(self, event: wx.ListEvent) -> None:
        """Open the artifact associated with an activated diagnostic row."""
        self._open_issue_location(event.GetIndex())

    def on_open_location(self, _event: wx.Event) -> None:
        """Open the artifact associated with the selected diagnostic row."""
        selected = self.issues.GetFirstSelected()
        if selected != -1:
            self._open_issue_location(selected)

    def on_export_report(self, _event: wx.Event) -> None:
        """Export the loaded trace index as a standalone HTML report."""
        with wx.FileDialog(
            self,
            message=_("Export Report"),
            defaultFile="trace_index_report.html",
            wildcard=_("HTML files (*.html)|*.html"),
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            try:
                self.export_report(Path(dialog.GetPath()))
            except (OSError, ValueError) as exc:
                wx.MessageBox(str(exc), _("Error"), parent=self)

    def export_report(self, path: Path) -> None:
        """Write a combined trace-index HTML report for the current index."""
        if self._index is None:
            raise ValueError(_("No trace index loaded."))
        matrix = build_artifact_trace_matrix(self._index)
        payload = render_trace_index_report_html(self._index, matrix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")

    def refresh(self, *, background: bool = True) -> None:
        """Refresh the index, optionally in a background worker for GUI use."""
        if self._refreshing:
            return
        self.config = self._config_from_controls()
        self._set_refreshing(True)
        self.status_label.SetLabel(_("Refreshing trace index…"))
        self._clear_issues()
        if background:
            self._worker = Thread(target=self._run_refresh_worker, daemon=True)
            self._worker.start()
        else:
            try:
                result = self._run_refresh_call()
            except Exception as exc:  # pragma: no cover - GUI defensive boundary
                self._show_refresh_error(exc)
            else:
                self._show_refresh_result(result)

    def _emit_index_changed(self, index: TraceIndex | None) -> None:
        if self._on_index_changed is not None:
            self._on_index_changed(index)

    def _show_cache_state(self) -> None:
        self.config = self._config_from_controls()
        cache_file = cache_path(self.req_root)
        self.cache_label.SetLabel(f"{_('Cache')}: {cache_file.as_posix()}")
        if not cache_file.exists():
            self.status_label.SetLabel(
                _("Trace index cache is missing. Refresh is recommended.")
            )
            self.summary_label.SetLabel("")
            self._clear_issues()
            self._index = None
            self._sync_export_report_button()
            self._emit_index_changed(None)
            return
        loaded = read_trace_index_cache_for_config(self.config)
        if loaded.index is None:
            self.status_label.SetLabel(_("Trace index cache is unreadable."))
            self.summary_label.SetLabel("")
            self._populate_issues(list(loaded.issues))
            self._index = None
            self._sync_export_report_button()
            self._emit_index_changed(None)
            return
        self._index = loaded.index
        self._show_index_summary(loaded.index)
        self._populate_issues(list(loaded.index.issues) + list(loaded.issues))
        self._sync_export_report_button()
        self._emit_index_changed(loaded.index)
        if loaded.stale:
            self.status_label.SetLabel(
                _("Trace index cache is stale. Refresh is recommended.")
            )
        else:
            self.status_label.SetLabel(_("Trace index cache is up to date."))

    def _run_refresh_worker(self) -> None:
        self._finish_refresh_call(self._run_refresh_call)

    def _finish_refresh_call(self, call: Callable[[], TraceIndexRefreshResult]) -> None:
        try:
            result = call()
        except Exception as exc:  # pragma: no cover - GUI defensive boundary
            wx.CallAfter(self._show_refresh_error, exc)
            return
        wx.CallAfter(self._show_refresh_result, result)

    def _run_refresh_call(self) -> TraceIndexRefreshResult:
        return self._refresh_runner(self.config)

    @staticmethod
    def _refresh_index(config: TraceIndexConfig) -> TraceIndexRefreshResult:
        index = build_trace_index(config)
        cache_file = write_trace_index_cache(index, config.req_root)
        return TraceIndexRefreshResult(index=index, cache_file=cache_file)

    def _show_refresh_result(self, result: TraceIndexRefreshResult) -> None:
        self._index = result.index
        self._show_index_summary(result.index)
        self.cache_label.SetLabel(f"{_('Cache')}: {result.cache_file.as_posix()}")
        self._populate_issues(list(result.index.issues))
        self._emit_index_changed(result.index)
        if result.index.issues:
            self.status_label.SetLabel(_("Trace index refreshed with diagnostics."))
        else:
            self.status_label.SetLabel(_("Trace index refreshed successfully."))
        self._set_refreshing(False)

    def _show_refresh_error(self, exc: Exception) -> None:
        self.status_label.SetLabel(_("Failed to refresh trace index."))
        wx.MessageBox(str(exc), _("Error"), parent=self)
        self._set_refreshing(False)

    def _show_index_summary(self, index: TraceIndex) -> None:
        counts = {
            "requirements": len(index.requirements),
            "code_locations": len(index.code_locations),
            "test_cases": len(index.test_cases),
            "test_runs": len(index.test_runs),
            "test_results": len(index.test_results),
        }
        self.summary_label.SetLabel(
            _(
                "Requirements: {requirements}  "
                "Code locations: {code_locations}  "
                "Test cases: {test_cases}  "
                "Test runs: {test_runs}  "
                "Test results: {test_results}"
            ).format(**counts)
        )

    def _populate_issues(self, issues: list[TraceIssue]) -> None:
        self._clear_issues()
        for issue in issues:
            row = self._issue_row(issue)
            self._issue_rows.append(row)
            index = self.issues.GetItemCount()
            self.issues.InsertItem(index, issue.severity)
            self.issues.SetItem(index, 1, issue.code)
            self.issues.SetItem(index, 2, row.location_text)
            self.issues.SetItem(index, 3, issue.message)
        self._sync_open_location_button()

    def _issue_row(self, issue: TraceIssue) -> TraceIssueRow:
        location = issue.path or ""
        artifact_path = self._resolve_issue_path(issue.path)
        if issue.line is not None:
            location = f"{location}:{issue.line}" if location else f"line {issue.line}"
        subject = issue.rid or issue.test_id or ""
        if subject:
            location = f"{location} {subject}".strip()
        return TraceIssueRow(
            issue=issue,
            location_text=location,
            artifact_path=artifact_path,
            line=issue.line,
        )

    def _resolve_issue_path(self, path: str | None) -> Path | None:
        if not path:
            return None
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.project_root / candidate
        try:
            resolved = candidate.resolve(strict=False)
            project_root = self.project_root.resolve(strict=False)
            resolved.relative_to(project_root)
        except (OSError, ValueError):
            return None
        return resolved

    def _open_issue_location(self, index: int) -> None:
        if index < 0 or index >= len(self._issue_rows):
            return
        row = self._issue_rows[index]
        if row.artifact_path is None:
            wx.MessageBox(
                _("This diagnostic is not associated with a project file."),
                _("No Location"),
                parent=self,
            )
            return
        if not row.artifact_path.is_file():
            wx.MessageBox(
                _("Artifact file does not exist: {path}").format(
                    path=row.artifact_path.as_posix()
                ),
                _("No Location"),
                parent=self,
            )
            return
        frame = TraceArtifactFrame(
            self,
            path=row.artifact_path,
            project_root=self.project_root,
            line=row.line,
        )
        frame.Show()

    def _clear_issues(self) -> None:
        self._issue_rows.clear()
        self.issues.DeleteAllItems()
        self._sync_open_location_button()

    def _set_refreshing(self, refreshing: bool) -> None:
        self._refreshing = refreshing
        self.refresh_button.Enable(not refreshing)
        self._sync_open_location_button()
        self._sync_export_report_button()

    def _sync_export_report_button(self) -> None:
        enabled = not self._refreshing and self._index is not None
        self.export_report_button.Enable(enabled)

    def _sync_open_location_button(self) -> None:
        selected = self.issues.GetFirstSelected()
        enabled = (
            not self._refreshing
            and selected != -1
            and selected < len(self._issue_rows)
            and self._issue_rows[selected].artifact_path is not None
        )
        self.open_location_button.Enable(enabled)


class TraceIndexFrame(wx.Frame):
    """Top-level window hosting the external evidence trace-index tab."""

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        req_root: Path,
        project_root: Path | None = None,
    ) -> None:
        super().__init__(parent, title=_("Trace Index"), size=(980, 620))
        project = (
            Path(project_root) if project_root is not None else Path(req_root).parent
        )
        notebook = wx.Notebook(self)
        self.artifact_browser_panel = TraceArtifactBrowserPanel(
            notebook,
            project_root=project,
        )
        self.artifact_matrix_panel = TraceArtifactMatrixPanel(
            notebook,
            project_root=project,
            on_requirement_focus=self.artifact_browser_panel.focus_rid,
        )
        self.trace_panel = TraceIndexPanel(
            notebook,
            req_root=req_root,
            project_root=project,
            on_index_changed=self._set_index,
        )
        notebook.AddPage(self.trace_panel, _("Trace"))
        notebook.AddPage(self.artifact_browser_panel, _("Artifact Browser"))
        notebook.AddPage(self.artifact_matrix_panel, _("Artifact Matrix"))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(notebook, 1, wx.EXPAND)
        self.SetSizer(sizer)

    def _set_index(self, index: TraceIndex | None) -> None:
        self.artifact_browser_panel.set_index(index)
        self.artifact_matrix_panel.set_index(index)


def _format_globs(globs: tuple[str, ...]) -> str:
    return "; ".join(globs)


def _parse_globs(value: str) -> tuple[str, ...]:
    parts = value.replace("\n", ";").split(";")
    return tuple(part.strip() for part in parts if part.strip())
