"""Tests for persisting MainFrame log level selection."""

import logging
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.gui


def test_log_level_persistence(wx_app, tmp_path, gui_context):
    pytest.importorskip("wx")
    from app.config import ConfigManager
    from app.settings import MCPSettings
    from app.ui.main_frame import MainFrame
    from app.ui.requirement_model import RequirementModel

    config_path = tmp_path / "cfg.ini"
    config = ConfigManager(path=config_path)
    config.set_log_level(logging.ERROR)
    config.set_mcp_settings(MCPSettings(auto_start=False))

    frame = MainFrame(None, context=gui_context, config=config, model=RequirementModel())
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

