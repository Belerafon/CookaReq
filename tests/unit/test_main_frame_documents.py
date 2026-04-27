from pathlib import Path

from types import SimpleNamespace

import wx

from app.core.document_store import Document, SharedArtifact
from app.core.trace_matrix import TraceDirection, TraceMatrixAxisConfig, TraceMatrixConfig
from app.settings import MCPSettings
from app.ui.main_frame.documents import (
    MainFrameDocumentsMixin,
    _infer_trace_direction,
    _recover_trace_matrix_direction,
)


class _StubConfig:
    def __init__(self) -> None:
        self.updated_settings: MCPSettings | None = None

    def set_mcp_settings(self, settings: MCPSettings) -> None:
        self.updated_settings = settings


class _StubMCPController:
    def __init__(self, running: bool = False) -> None:
        self._running = running
        self.stop_calls = 0
        self.start_calls = 0
        self.started_with: MCPSettings | None = None

    def is_running(self) -> bool:
        return self._running

    def stop(self) -> None:
        self.stop_calls += 1
        self._running = False

    def start(self, settings: MCPSettings, **_: object) -> None:
        self.start_calls += 1
        self.started_with = settings
        self._running = True


class _StubFrame(MainFrameDocumentsMixin):
    def __init__(self, *, running: bool, auto_start: bool, base_path: Path) -> None:
        self.config = _StubConfig()
        self.mcp_settings = MCPSettings(
            auto_start=auto_start,
            base_path=str(base_path),
        )
        self.mcp = _StubMCPController(running=running)
        self.llm_settings = SimpleNamespace(
            max_context_tokens=4096,
            model="test-model",
        )


def test_sync_mcp_base_path_restarts_running_server_when_auto_start_disabled(tmp_path):
    original = tmp_path / "old"
    new_path = tmp_path / "new"
    original.mkdir()
    new_path.mkdir()

    frame = _StubFrame(running=True, auto_start=False, base_path=original)

    frame._sync_mcp_base_path(new_path)

    assert frame.mcp.stop_calls == 1
    assert frame.mcp.start_calls == 1
    assert frame.mcp.started_with is frame.mcp_settings
    assert frame.mcp_settings.base_path == str(new_path.resolve())
    assert frame.config.updated_settings is frame.mcp_settings


def test_sync_mcp_base_path_avoids_restart_when_server_idle(tmp_path):
    original = tmp_path / "old"
    new_path = tmp_path / "new"
    original.mkdir()
    new_path.mkdir()

    frame = _StubFrame(running=False, auto_start=False, base_path=original)

    frame._sync_mcp_base_path(new_path)

    assert frame.mcp.stop_calls == 0
    assert frame.mcp.start_calls == 0
    assert frame.mcp_settings.base_path == str(new_path.resolve())
    assert frame.config.updated_settings is frame.mcp_settings


class _StubPanel:
    def __init__(self, *, selected_ids: list[int], has_filters: bool) -> None:
        self._selected_ids = selected_ids
        self._has_filters = has_filters

    def get_selected_ids(self) -> list[int]:
        return list(self._selected_ids)

    def has_active_filters(self) -> bool:
        return self._has_filters


class _ScopeFrame(MainFrameDocumentsMixin):
    def __init__(self, *, selected_ids: list[int], has_filters: bool) -> None:
        self.panel = _StubPanel(selected_ids=selected_ids, has_filters=has_filters)


def test_default_export_scope_prefers_selected_over_filters() -> None:
    frame = _ScopeFrame(selected_ids=[1, 2], has_filters=True)

    assert frame._default_export_scope() == "selected"


def test_default_export_scope_uses_visible_when_filters_active() -> None:
    frame = _ScopeFrame(selected_ids=[1], has_filters=True)

    assert frame._default_export_scope() == "visible"


def test_default_export_scope_falls_back_to_all() -> None:
    frame = _ScopeFrame(selected_ids=[], has_filters=False)

    assert frame._default_export_scope() == "all"


def test_default_document_export_scope_is_current() -> None:
    frame = _ScopeFrame(selected_ids=[], has_filters=False)

    assert frame._default_document_export_scope() == "current"


class _SummaryFrame(MainFrameDocumentsMixin):
    def __init__(self) -> None:
        self.current_doc_prefix = "SYS"
        self.docs_controller = SimpleNamespace(
            documents={
                "SYS": Document(
                    prefix="SYS",
                    title="System",
                    attributes={"doc_revision": 5},
                )
            }
        )


def test_current_document_summary_includes_revision() -> None:
    frame = _SummaryFrame()

    assert frame._current_document_summary() == "SYS: System (rev 5)"


def test_infer_trace_direction_defaults_to_parent_to_child_for_parent_rows() -> None:
    docs = {
        "SYS": Document(prefix="SYS", title="System"),
        "HLR": Document(prefix="HLR", title="High", parent="SYS"),
        "LLR": Document(prefix="LLR", title="Low", parent="HLR"),
    }

    direction = _infer_trace_direction(docs, row_prefix="SYS", column_prefix="HLR")

    assert direction is TraceDirection.PARENT_TO_CHILD


def test_infer_trace_direction_keeps_child_to_parent_for_child_rows() -> None:
    docs = {
        "SYS": Document(prefix="SYS", title="System"),
        "HLR": Document(prefix="HLR", title="High", parent="SYS"),
    }

    direction = _infer_trace_direction(docs, row_prefix="HLR", column_prefix="SYS")

    assert direction is TraceDirection.CHILD_TO_PARENT


def test_recover_trace_matrix_direction_switches_to_reverse_when_only_reverse_has_links() -> None:
    config = TraceMatrixConfig(
        rows=TraceMatrixAxisConfig(documents=("SYS",)),
        columns=TraceMatrixAxisConfig(documents=("HLR",)),
        direction=TraceDirection.CHILD_TO_PARENT,
    )
    matrix = SimpleNamespace(summary=SimpleNamespace(linked_pairs=0))

    class _Controller:
        def build_trace_matrix(self, cfg):
            linked = 6 if cfg.direction is TraceDirection.PARENT_TO_CHILD else 0
            return SimpleNamespace(summary=SimpleNamespace(linked_pairs=linked))

    recovered_config, recovered_matrix, recovered = _recover_trace_matrix_direction(
        _Controller(),
        config,
        matrix,
    )

    assert recovered is True
    assert recovered_config.direction is TraceDirection.PARENT_TO_CHILD
    assert recovered_matrix.summary.linked_pairs == 6


def test_recover_trace_matrix_direction_keeps_original_when_reverse_not_better() -> None:
    config = TraceMatrixConfig(
        rows=TraceMatrixAxisConfig(documents=("HLR",)),
        columns=TraceMatrixAxisConfig(documents=("SYS",)),
        direction=TraceDirection.CHILD_TO_PARENT,
    )
    matrix = SimpleNamespace(summary=SimpleNamespace(linked_pairs=6))

    class _Controller:
        def build_trace_matrix(self, cfg):
            return SimpleNamespace(summary=SimpleNamespace(linked_pairs=0))

    recovered_config, recovered_matrix, recovered = _recover_trace_matrix_direction(
        _Controller(),
        config,
        matrix,
    )

    assert recovered is False
    assert recovered_config is config
    assert recovered_matrix is matrix


def test_resolve_export_document_prefixes_orders_subtree() -> None:
    frame = _SummaryFrame()
    docs = {
        "SYS": Document(prefix="SYS", title="System"),
        "TVU": Document(prefix="TVU", title="Top", parent="SYS"),
        "HLR": Document(prefix="HLR", title="High"),
        "TNU": Document(prefix="TNU", title="Low", parent="TVU"),
    }

    prefixes = frame._resolve_export_document_prefixes(
        docs=docs,
        current_prefix="SYS",
        document_scope="subtree",
        manual_prefixes=[],
    )

    assert prefixes == ["SYS", "TVU", "TNU"]


def test_resolve_export_document_prefixes_orders_manual_selection() -> None:
    frame = _SummaryFrame()
    docs = {
        "SYS": Document(prefix="SYS", title="System"),
        "TVU": Document(prefix="TVU", title="Top", parent="SYS"),
        "HLR": Document(prefix="HLR", title="High"),
    }

    prefixes = frame._resolve_export_document_prefixes(
        docs=docs,
        current_prefix="SYS",
        document_scope="manual",
        manual_prefixes=["TVU", "SYS"],
    )

    assert prefixes == ["SYS", "TVU"]


class _ExportFrame(MainFrameDocumentsMixin):
    pass


def test_collect_context_preface_collects_unique_markdown_and_missing(tmp_path: Path) -> None:
    doc_root = tmp_path / "SYS"
    related = doc_root / "related"
    related.mkdir(parents=True)
    (related / "a.md").write_text("# A", encoding="utf-8")

    req1 = SimpleNamespace(rid="SYS1", context_docs=["related/a.md", "related/missing.md"])
    req2 = SimpleNamespace(rid="SYS2", context_docs=["related/a.md", "../escape.md"])
    req3 = SimpleNamespace(rid="SYS3", context_docs="bad")

    frame = _ExportFrame()
    preface, missing = frame._collect_context_preface([req1, req2, req3], doc_root=doc_root)

    assert preface == [("related/a.md", "# A")]
    assert any("SYS1" in line and "related/missing.md" in line for line in missing)
    assert any("SYS2" in line and "outside document root" in line for line in missing)
    assert any("SYS3" in line and "invalid context_docs format" in line for line in missing)


def test_collect_shared_artifacts_preface_includes_only_enabled_and_converts_formats(tmp_path: Path) -> None:
    doc_root = tmp_path / "SYS"
    shared = doc_root / "shared"
    shared.mkdir(parents=True)
    (shared / "overview.md").write_text("# Overview", encoding="utf-8")
    (shared / "matrix.csv").write_text("a,b\n1,2", encoding="utf-8")

    document = Document(
        prefix="SYS",
        title="System",
        shared_artifacts=[
            SharedArtifact(id="A1", path="shared/overview.md", title="Overview", include_in_export=True),
            SharedArtifact(id="A2", path="shared/matrix.csv", title="Matrix", include_in_export=True),
            SharedArtifact(id="A3", path="shared/missing.txt", title="Missing", include_in_export=True),
            SharedArtifact(id="A4", path="shared/hidden.txt", title="Hidden", include_in_export=False),
        ],
    )

    frame = _ExportFrame()
    preface, missing = frame._collect_shared_artifacts_preface(document, doc_root=doc_root)

    assert preface[0] == ("Overview", "# Overview")
    assert preface[1][0] == "Matrix"
    assert preface[1][1].startswith("```csv\n")
    assert any("shared/missing.txt" in line for line in missing)


def test_render_preface_header_lines_flattens_markdown_lines() -> None:
    frame = _ExportFrame()

    lines = frame._render_preface_header_lines([("Spec", "# Title\n\nvalue")])

    assert lines == ["Context: Spec", "# Title", "value"]


class _WorkspaceExportFrame(MainFrameDocumentsMixin):
    def __init__(self, current_dir: Path | None) -> None:
        self.current_dir = current_dir


def test_recommended_export_directory_uses_sibling_folder(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    frame = _WorkspaceExportFrame(current_dir=workspace)

    assert frame._recommended_export_directory() == tmp_path / "project_exports"


def test_is_workspace_root_export_target_matches_parent_directory(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    frame = _WorkspaceExportFrame(current_dir=workspace)

    assert frame._is_workspace_root_export_target(workspace / "export.txt") is True
    assert frame._is_workspace_root_export_target(workspace / "nested" / "export.txt") is False


def test_warn_workspace_root_export_requires_reselect(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    frame = _WorkspaceExportFrame(current_dir=workspace)
    calls: list[tuple[str, str, int]] = []

    def _message_box(message: str, title: str, style: int) -> int:
        calls.append((message, title, style))
        return wx.OK

    monkeypatch.setattr("app.ui.main_frame.documents.wx.MessageBox", _message_box)

    proceed = frame._warn_workspace_root_export(
        target_path=workspace / "archive.zip",
        export_label="project archive",
    )

    assert proceed is False
    assert calls
    _, _, style = calls[0]
    assert style == wx.OK | wx.CANCEL | wx.ICON_WARNING


def test_warn_workspace_root_export_cancel_aborts(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    frame = _WorkspaceExportFrame(current_dir=workspace)

    monkeypatch.setattr(
        "app.ui.main_frame.documents.wx.MessageBox",
        lambda *_args, **_kwargs: wx.CANCEL,
    )

    proceed = frame._warn_workspace_root_export(
        target_path=workspace / "archive.zip",
        export_label="project archive",
    )

    assert proceed is None
