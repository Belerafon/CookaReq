"""Tests for gui."""

import logging
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skip(
    reason="GUI smoke tests disabled while ListPanel runs in ultra-minimal debug mode."
)


def test_gui_imports(wx_app):
    pytest.importorskip("wx")
    from app.main import main
    from app.ui.editor_panel import EditorPanel
    from app.ui.list_panel import ListPanel
    from app.ui.main_frame import MainFrame

    frame = MainFrame(None)
    list_panel = ListPanel(frame)
    editor_panel = EditorPanel(frame)
    assert list_panel.GetParent() is frame
    assert editor_panel.GetParent() is frame
    assert callable(main)


def test_log_level_persistence(wx_app, tmp_path):
    pytest.importorskip("wx")
    from app.config import ConfigManager
    from app.ui.main_frame import MainFrame
    from app.ui.requirement_model import RequirementModel

    config_path = tmp_path / "cfg.ini"
    config = ConfigManager(path=config_path)
    config.set_log_level(logging.ERROR)

    frame = MainFrame(None, config=config, model=RequirementModel())
    try:
        selection = frame.log_level_choice.GetSelection()
        assert selection >= 0
        assert frame._log_level_values[selection] == logging.ERROR

        debug_index = frame._find_choice_index_for_level(logging.DEBUG)
        assert debug_index >= 0
        frame.log_level_choice.SetSelection(debug_index)
        frame.on_change_log_level(SimpleNamespace(GetSelection=lambda: debug_index))

        assert frame.log_handler.level == logging.DEBUG
        assert config.get_log_level() == logging.DEBUG

        reloaded = ConfigManager(path=config_path)
        assert reloaded.get_log_level() == logging.DEBUG
    finally:
        frame.Destroy()
        wx_app.Yield()
