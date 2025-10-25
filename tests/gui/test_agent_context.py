import shutil
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
        assert "Active requirements document" in content
        assert "Selected requirement RIDs:" in content
        assert "GUI selection #" not in content
        assert "(id=" not in content
        assert "prefix=" not in content
        assert "DEMO1" in content
        assert "DEMO2" in content
        assert "[User documentation]" in content
        assert "Directory tree:" in content
        assert "ГОСТ требования.txt" in content
        assert "папка с пробелами" in content
    finally:
        frame.Destroy()
        wx_app.Yield()
