"""Tests for application icon handling."""

import wx

from app.ui.main_frame import MainFrame


def test_main_frame_loads_multiple_icon_sizes(wx_app):
    """Main frame should expose all icon sizes for taskbar usage."""
    frame = MainFrame(None)
    try:
        bundle = frame.GetIcons()
        assert bundle.GetIconCount() >= 2
    finally:
        frame.Destroy()

