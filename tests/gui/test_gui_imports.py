"""Tests that basic GUI components can be imported and instantiated."""

import pytest


pytestmark = pytest.mark.gui


def test_gui_imports(wx_app, tmp_path, gui_context):
    pytest.importorskip("wx")
    from app.config import ConfigManager
    from app.settings import MCPSettings
    from app.ui.editor_panel import EditorPanel
    from app.ui.list_panel import ListPanel
    from app.ui.main_frame import MainFrame
    from app.main import main

    config = ConfigManager(path=tmp_path / "gui.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))

    frame = MainFrame(None, context=gui_context, config=config)
    list_panel = ListPanel(frame)
    editor_panel = EditorPanel(frame)

    assert callable(main)
    assert list_panel.GetParent() is frame
    assert editor_panel.GetParent() is frame

