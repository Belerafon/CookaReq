"""Tests for the MainFrame view menu behavior."""

import pytest


pytestmark = pytest.mark.gui


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

