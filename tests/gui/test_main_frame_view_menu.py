"""Tests for the MainFrame view menu behavior."""

import pytest


pytestmark = pytest.mark.gui


def test_view_menu_hides_legacy_derived_from_column(wx_app, tmp_path, gui_context):
    pytest.importorskip("wx")
    from app.config import ConfigManager
    from app.settings import MCPSettings
    from app.ui.main_frame import MainFrame

    config = ConfigManager(path=tmp_path / "columns.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))

    frame = MainFrame(None, context=gui_context, config=config)
    try:
        assert "derived_from" not in frame.available_fields
        assert all(
            field != "derived_from"
            for field in frame.navigation._column_items.values()
        )
    finally:
        frame.Destroy()
        wx_app.Yield()
