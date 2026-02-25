from pathlib import Path

from types import SimpleNamespace

from app.core.document_store import Document
from app.settings import MCPSettings
from app.ui.main_frame.documents import MainFrameDocumentsMixin


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
