"""GUI tests for the external evidence trace-index panel."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.core.trace_index import build_trace_index, write_trace_index_cache
from app.ui.trace_index import (
    TraceArtifactBrowserPanel,
    TraceArtifactMatrixPanel,
    TraceIndexFrame,
    TraceIndexPanel,
)
from app.ui.trace_index.trace_tab import TraceIndexRefreshResult
import app.ui.trace_index.trace_tab as trace_tab_module

pytestmark = pytest.mark.gui

FIXTURE_ROOT = Path("tests/fixtures/trace_index_project")


def _copy_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "trace_index_project"
    shutil.copytree(FIXTURE_ROOT, target)
    return target


def test_trace_index_panel_refresh_writes_cache_and_summary(wx_app, tmp_path):
    """Refreshing from the GUI panel builds the index and displays its summary."""

    _wx = pytest.importorskip("wx")
    root = _copy_fixture(tmp_path)
    frame = _wx.Frame(None)
    try:
        panel = TraceIndexPanel(
            frame,
            req_root=root / "Req",
            project_root=root,
        )

        panel.exclude_globs_text.SetValue("Vsrc/broken_*")
        panel.refresh(background=False)

        cache_path = root / "Req" / ".cookareq" / "trace_index.generated.json"
        assert cache_path.exists()
        assert "Requirements: 12" in panel.summary_label.GetLabel()
        assert "Test results: 5" in panel.summary_label.GetLabel()
        assert panel.issues.GetItemCount() == 0
        assert "successfully" in panel.status_label.GetLabel()
    finally:
        frame.Destroy()


def test_trace_index_panel_scan_settings_feed_refresh_config(wx_app, tmp_path):
    """Refresh uses scan settings entered in the GUI controls."""

    _wx = pytest.importorskip("wx")
    root = _copy_fixture(tmp_path)
    seen = []

    def _runner(config):
        seen.append(config)
        index = build_trace_index(config)
        return TraceIndexRefreshResult(
            index=index,
            cache_file=write_trace_index_cache(index, config.req_root),
        )

    frame = _wx.Frame(None)
    try:
        panel = TraceIndexPanel(
            frame,
            req_root=root / "Req",
            project_root=root,
            refresh_runner=_runner,
        )

        panel.module_filter_text.SetValue("V_pid_reg3")
        panel.source_globs_text.SetValue("Vsrc/V_pid_reg3.c; Vinclude/V_pid_reg3.h")
        panel.test_globs_text.SetValue("tests/test_V_pid_reg3/src/*.c")
        panel.result_globs_text.SetValue("tests/test_V_pid_reg3/Build/test_results.txt")
        panel.exclude_globs_text.SetValue("Vsrc/broken_*")
        panel.refresh(background=False)

        assert seen
        config = seen[-1]
        assert config.module_filter == "V_pid_reg3"
        assert config.source_globs == ("Vsrc/V_pid_reg3.c", "Vinclude/V_pid_reg3.h")
        assert config.test_globs == ("tests/test_V_pid_reg3/src/*.c",)
        assert config.result_globs == ("tests/test_V_pid_reg3/Build/test_results.txt",)
        assert panel.summary_label.GetLabel().startswith("Requirements: 10")
    finally:
        frame.Destroy()


def test_trace_index_panel_opens_diagnostic_artifact(wx_app, tmp_path, monkeypatch):
    """A diagnostic row can open the related project artifact at its line."""

    _wx = pytest.importorskip("wx")
    root = _copy_fixture(tmp_path)
    opened: list[tuple[Path, int | None, Path]] = []

    class _ArtifactFrameStub:
        def __init__(
            self,
            parent,
            *,
            path: Path,
            project_root: Path,
            line: int | None = None,
        ):
            self.parent = parent
            opened.append((path, line, project_root))

        def Show(self):
            return None

    monkeypatch.setattr(trace_tab_module, "TraceArtifactFrame", _ArtifactFrameStub)
    frame = _wx.Frame(None)
    try:
        panel = TraceIndexPanel(
            frame,
            req_root=root / "Req",
            project_root=root,
        )

        panel.refresh(background=False)
        panel.issues.Select(0)
        panel.on_open_location(_wx.CommandEvent())

        assert opened == [(root / "Vsrc" / "broken_marker.c", 2, root)]
        assert panel.open_location_button.IsEnabled()
    finally:
        frame.Destroy()


def test_trace_index_refresh_populates_artifact_browser(wx_app, tmp_path):
    """Refreshing the Trace tab feeds artifacts into the browser tab."""

    _wx = pytest.importorskip("wx")
    root = _copy_fixture(tmp_path)
    frame = TraceIndexFrame(None, req_root=root / "Req", project_root=root)
    try:
        frame.trace_panel.exclude_globs_text.SetValue("Vsrc/broken_*")
        frame.trace_panel.refresh(background=False)

        browser = frame.artifact_browser_panel
        assert browser.artifacts.GetItemCount() == 30
        first_types = {
            browser.artifacts.GetItemText(index)
            for index in range(browser.artifacts.GetItemCount())
        }
        assert {"Code", "Test Case", "Test Result"}.issubset(first_types)
    finally:
        frame.Destroy()


def test_trace_index_refresh_populates_artifact_matrix(wx_app, tmp_path):
    """Refreshing the Trace tab feeds the requirement x artifact matrix tab."""

    _wx = pytest.importorskip("wx")
    root = _copy_fixture(tmp_path)
    frame = TraceIndexFrame(None, req_root=root / "Req", project_root=root)
    try:
        frame.trace_panel.exclude_globs_text.SetValue("Vsrc/broken_*")
        frame.trace_panel.refresh(background=False)

        matrix = frame.artifact_matrix_panel
        assert matrix.matrix.GetItemCount() == 12
        assert matrix.matrix.GetColumnCount() == 32
        assert "12 requirements x 30 artifacts" in matrix.status_label.GetLabel()

        llr10_row = next(
            index
            for index in range(matrix.matrix.GetItemCount())
            if matrix.matrix.GetItemText(index) == "LLR10"
        )
        row_values = [
            matrix.matrix.GetItemText(llr10_row, column)
            for column in range(matrix.matrix.GetColumnCount())
        ]
        assert "passed" in row_values
        assert "Code" in row_values
        assert "Test Case" in row_values
    finally:
        frame.Destroy()


def test_trace_index_artifact_matrix_exports_files(wx_app, tmp_path):
    """Artifact Matrix can export the current matrix as CSV and HTML."""

    pytest.importorskip("wx")
    root = _copy_fixture(tmp_path)
    frame = TraceIndexFrame(None, req_root=root / "Req", project_root=root)
    try:
        frame.trace_panel.exclude_globs_text.SetValue("Vsrc/broken_*")
        frame.trace_panel.refresh(background=False)
        matrix = frame.artifact_matrix_panel

        json_path = tmp_path / "exports" / "artifact_matrix.json"
        csv_path = tmp_path / "exports" / "artifact_matrix.csv"
        html_path = tmp_path / "exports" / "artifact_matrix.html"
        matrix.export_matrix(json_path, format_id="json")
        matrix.export_matrix(csv_path, format_id="csv")
        matrix.export_matrix(html_path, format_id="html")

        json_text = json_path.read_text(encoding="utf-8")
        csv_text = csv_path.read_text(encoding="utf-8")
        html_text = html_path.read_text(encoding="utf-8")
        assert "\"requirements\"" in json_text
        assert "LLR10" in json_text
        assert csv_text.startswith("Requirement,Title,code:")
        assert "LLR10" in csv_text
        assert "passed" in csv_text
        assert "<table>" in html_text
        assert "Trace Index Artifact Matrix" in html_text
        assert "LLR10" in html_text
        assert matrix.export_json_button.IsEnabled()
        assert matrix.export_csv_button.IsEnabled()
        assert matrix.export_html_button.IsEnabled()
    finally:
        frame.Destroy()


def test_trace_index_artifact_matrix_focuses_browser_by_selected_requirement(
    wx_app, tmp_path
):
    """Artifact Matrix can focus Artifact Browser to the selected RID."""

    pytest.importorskip("wx")
    root = _copy_fixture(tmp_path)
    frame = TraceIndexFrame(None, req_root=root / "Req", project_root=root)
    try:
        frame.trace_panel.exclude_globs_text.SetValue("Vsrc/broken_*")
        frame.trace_panel.refresh(background=False)
        matrix = frame.artifact_matrix_panel
        browser = frame.artifact_browser_panel

        llr10_row = next(
            index
            for index in range(matrix.matrix.GetItemCount())
            if matrix.matrix.GetItemText(index) == "LLR10"
        )
        matrix.matrix.Select(llr10_row)
        matrix.on_selection_changed(_event=None)
        matrix.on_focus_browser(_event=None)

        assert matrix.selected_requirement_rid() == "LLR10"
        assert matrix.focus_browser_button.IsEnabled()
        assert browser.rid_filter.GetValue() == "LLR10"
        assert browser.artifacts.GetItemCount() > 0
        for index in range(browser.artifacts.GetItemCount()):
            assert "LLR10" in browser.artifacts.GetItemText(index, 2)
    finally:
        frame.Destroy()

def test_trace_index_artifact_browser_filters_rows(wx_app, tmp_path):
    """Artifact Browser filters by type and RID without rebuilding the index."""

    _wx = pytest.importorskip("wx")
    root = _copy_fixture(tmp_path)
    frame = TraceIndexFrame(None, req_root=root / "Req", project_root=root)
    try:
        frame.trace_panel.exclude_globs_text.SetValue("Vsrc/broken_*")
        frame.trace_panel.refresh(background=False)
        browser = frame.artifact_browser_panel

        browser.type_filter.SetStringSelection("Test Result")
        browser.on_apply_filter(_wx.CommandEvent())
        assert browser.artifacts.GetItemCount() == 5
        assert "5 of 30" in browser.status_label.GetLabel()

        browser.rid_filter.SetValue("LLR10")
        browser.on_apply_filter(_wx.CommandEvent())
        assert browser.artifacts.GetItemCount() == 1

        browser.on_clear_filter(_wx.CommandEvent())
        assert browser.artifacts.GetItemCount() == 30
    finally:
        frame.Destroy()


def test_trace_index_artifact_browser_groups_by_requirement(wx_app, tmp_path):
    """Artifact Browser can expand multi-RID artifacts into requirement rows."""

    _wx = pytest.importorskip("wx")
    root = _copy_fixture(tmp_path)
    frame = TraceIndexFrame(None, req_root=root / "Req", project_root=root)
    try:
        frame.trace_panel.exclude_globs_text.SetValue("Vsrc/broken_*")
        frame.trace_panel.refresh(background=False)
        browser = frame.artifact_browser_panel

        browser.group_by_rid.SetValue(True)
        browser.on_grouping_changed(_wx.CommandEvent())
        grouped_count = browser.artifacts.GetItemCount()
        assert grouped_count > 30

        browser.rid_filter.SetValue("LLR10")
        browser.on_apply_filter(_wx.CommandEvent())
        assert 0 < browser.artifacts.GetItemCount() < grouped_count
        for index in range(browser.artifacts.GetItemCount()):
            assert browser.artifacts.GetItemText(index, 2) == "LLR10"
    finally:
        frame.Destroy()


def test_trace_index_artifact_browser_focuses_selected_rid(wx_app, tmp_path):
    """Focus RID narrows the browser to artifacts related to a selected requirement."""

    _wx = pytest.importorskip("wx")
    root = _copy_fixture(tmp_path)
    frame = TraceIndexFrame(None, req_root=root / "Req", project_root=root)
    try:
        frame.trace_panel.exclude_globs_text.SetValue("Vsrc/broken_*")
        frame.trace_panel.refresh(background=False)
        browser = frame.artifact_browser_panel
        browser.group_by_rid.SetValue(True)
        browser.on_grouping_changed(_wx.CommandEvent())

        target_index = next(
            index
            for index in range(browser.artifacts.GetItemCount())
            if browser.artifacts.GetItemText(index, 2) == "LLR10"
        )
        browser.artifacts.Select(target_index)
        browser.on_focus_rid(_wx.CommandEvent())

        assert browser.rid_filter.GetValue() == "LLR10"
        assert browser.artifacts.GetItemCount() > 0
        for index in range(browser.artifacts.GetItemCount()):
            assert browser.artifacts.GetItemText(index, 2) == "LLR10"
    finally:
        frame.Destroy()


def test_trace_index_frame_hosts_trace_and_artifact_browser_tabs(wx_app, tmp_path):
    """The top-level frame exposes Trace and Artifact Browser tabs."""

    _wx = pytest.importorskip("wx")
    root = _copy_fixture(tmp_path)
    frame = TraceIndexFrame(None, req_root=root / "Req", project_root=root)
    try:
        notebook = next(
            (child for child in frame.GetChildren() if isinstance(child, _wx.Notebook)),
            None,
        )
        assert isinstance(notebook, _wx.Notebook)
        assert notebook.GetPageText(0) == "Trace"
        assert notebook.GetPageText(1) == "Artifact Browser"
        assert notebook.GetPageText(2) == "Artifact Matrix"
        assert isinstance(frame.trace_panel, TraceIndexPanel)
        assert isinstance(frame.artifact_browser_panel, TraceArtifactBrowserPanel)
        assert isinstance(frame.artifact_matrix_panel, TraceArtifactMatrixPanel)
    finally:
        frame.Destroy()
