import shutil
import threading
import time
from pathlib import Path

import pytest

from app.application import ApplicationContext

pytestmark = pytest.mark.gui

wx = pytest.importorskip("wx")


def _copy_sample_repository(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[2] / "requirements"
    destination = tmp_path / "requirements"
    shutil.copytree(source, destination)
    return destination


def _create_main_frame(tmp_path: Path):
    from app.config import ConfigManager
    from app.settings import MCPSettings
    from app.ui.main_frame import MainFrame
    from app.ui.requirement_model import RequirementModel

    config_path = tmp_path / "context.ini"
    config = ConfigManager(path=config_path)
    config.set_mcp_settings(MCPSettings(auto_start=False))
    frame = MainFrame(
        None,
        context=ApplicationContext.for_gui(),
        config=config,
        model=RequirementModel(),
    )
    frame.Show()
    return frame


def _wait_for(predicate, wx_app, timeout: float = 5.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        wx_app.Yield()
        if predicate():
            return True
        time.sleep(0.01)
    wx_app.Yield()
    return predicate()


def test_agent_context_includes_selected_requirements(tmp_path, wx_app):
    repository = _copy_sample_repository(tmp_path)
    docs_root = repository / "share"
    docs_root.mkdir()
    (docs_root / "ГОСТ требования.txt").write_text("Содержание", encoding="utf-8")
    nested = docs_root / "папка с пробелами"
    nested.mkdir()
    (nested / "описание.md").write_text("# Заголовок", encoding="utf-8")
    frame = _create_main_frame(tmp_path)

    try:
        wx_app.Yield()
        frame._load_directory(repository)
        wx_app.Yield()

        list_ctrl = frame.panel.list
        assert list_ctrl.GetItemCount() >= 2
        list_ctrl.Select(0)
        list_ctrl.Select(1, True)
        wx_app.Yield()

        messages = frame._agent_context_messages()
        assert messages
        snapshot = messages[0]
        assert snapshot["role"] == "system"
        content = snapshot["content"]
        if "Directory tree:" not in content:
            assert "Documentation folder is loading…" in content
            assert _wait_for(
                lambda: getattr(frame, "_documents_tree_cache", None) is not None,
                wx_app,
            )
            messages = frame._agent_context_messages()
            snapshot = messages[0]
            content = snapshot["content"]
        assert "Active requirements list" in content
        assert "Selected requirement RIDs:" in content
        assert "GUI selection #" not in content
        assert "(id=" not in content
        assert "prefix=" not in content
        assert "DEMO1" in content
        assert "DEMO2" in content
        assert "[User documentation]" in content
        assert "Directory tree:" in content
        assert "Snapshot generated at:" in content
        assert "ГОСТ требования.txt" in content
        assert "папка с пробелами" in content
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_user_documents_tree_loads_in_background(tmp_path, wx_app, monkeypatch):
    from app.services.user_documents import UserDocumentsService

    repository = _copy_sample_repository(tmp_path)
    docs_root = repository / "share"
    docs_root.mkdir()
    (docs_root / "manual.txt").write_text("Contents", encoding="utf-8")
    frame = _create_main_frame(tmp_path)

    start_event = threading.Event()
    release_event = threading.Event()
    thread_refs: list[threading.Thread] = []

    def fake_list_tree(self):
        thread_refs.append(threading.current_thread())
        start_event.set()
        release_event.wait(timeout=5)
        return {
            "max_context_tokens": self.max_context_tokens,
            "max_read_bytes": self.max_read_bytes,
            "max_read_kib": self.max_read_bytes // 1024,
            "token_model": self.token_model,
            "tree_text": "manual.txt",
        }

    monkeypatch.setattr(UserDocumentsService, "list_tree", fake_list_tree)

    try:
        wx_app.Yield()
        frame._load_directory(repository)
        wx_app.Yield()

        list_ctrl = frame.panel.list
        list_ctrl.Select(0)
        wx_app.Yield()

        messages = frame._agent_context_messages()
        assert "Documentation folder is loading…" in messages[0]["content"]
        assert start_event.wait(timeout=5)
        assert thread_refs, "background task did not start"
        assert thread_refs[0] is not threading.main_thread()

        assert getattr(frame, "_documents_tree_cache", None) is None
        release_event.set()
        assert _wait_for(
            lambda: getattr(frame, "_documents_tree_cache", None) is not None,
            wx_app,
        )

        messages = frame._agent_context_messages()
        content = messages[0]["content"]
        assert "manual.txt" in content
        assert "Directory tree:" in content
    finally:
        release_event.set()
        frame.Destroy()
        wx_app.Yield()
