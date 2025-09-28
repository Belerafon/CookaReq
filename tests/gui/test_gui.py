"""Tests for gui."""

import logging
from types import SimpleNamespace

import pytest

from app.config import ConfigManager
from app.settings import MCPSettings

pytestmark = pytest.mark.gui


def test_gui_imports(wx_app, tmp_path, gui_context):
    pytest.importorskip("wx")
    from app.main import main
    from app.ui.editor_panel import EditorPanel
    from app.ui.list_panel import ListPanel
    from app.ui.main_frame import MainFrame

    config = ConfigManager(path=tmp_path / "gui.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))

    frame = MainFrame(None, context=gui_context, config=config)
    list_panel = ListPanel(frame)
    editor_panel = EditorPanel(frame)
    assert list_panel.GetParent() is frame
    assert editor_panel.GetParent() is frame
    assert callable(main)


def test_view_menu_lists_derived_from_column(wx_app, tmp_path, gui_context):
    pytest.importorskip("wx")
    from app.config import ConfigManager
    from app.settings import MCPSettings
    from app.ui.main_frame import MainFrame

    config = ConfigManager(path=tmp_path / "columns.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))

    frame = MainFrame(None, context=gui_context, config=config)
    try:
        assert "derived_from" in frame.available_fields
        derived_items = [
            item_id
            for item_id, field in frame.navigation._column_items.items()
            if field == "derived_from"
        ]
        assert derived_items, "Derived from column should appear in the Columns menu"
        for item_id in derived_items:
            menu_item = frame.navigation.menu_bar.FindItemById(item_id)
            assert menu_item is not None
            assert menu_item.IsCheckable()
            assert menu_item.IsChecked()
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_log_level_persistence(wx_app, tmp_path, gui_context):
    pytest.importorskip("wx")
    from app.config import ConfigManager
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
