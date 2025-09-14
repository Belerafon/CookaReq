"""Tests for application icon handling."""

import pytest

from app.ui.main_frame import MainFrame

pytestmark = pytest.mark.gui


def test_main_frame_loads_multiple_icon_sizes(wx_app):
    """Main frame should expose all icon sizes for taskbar usage."""
    pytest.importorskip("wx")
    frame = MainFrame(None)
    try:
        bundle = frame.GetIcons()
        assert bundle.GetIconCount() >= 2
    finally:
        frame.Destroy()

