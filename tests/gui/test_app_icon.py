"""Tests for application icon handling."""

import pytest

from app.config import ConfigManager
from app.settings import MCPSettings
from app.ui.main_frame import MainFrame

pytestmark = pytest.mark.gui


def test_main_frame_loads_multiple_icon_sizes(wx_app, tmp_path):
    """Main frame should expose all icon sizes for taskbar usage."""
    pytest.importorskip("wx")
    config = ConfigManager(path=tmp_path / "icons.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))

    frame = MainFrame(None, config=config)
    try:
        bundle = frame.GetIcons()
        assert bundle.GetIconCount() >= 2
    finally:
        frame.Destroy()
