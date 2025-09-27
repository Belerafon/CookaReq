from contextlib import suppress

import pytest
import wx

from app.ui.helpers import HelpStaticBox

pytestmark = pytest.mark.gui


def _noop(anchor: wx.Window, msg: str) -> None:  # pragma: no cover - placeholder callback
    pass


def test_help_static_box_handles_prepend_and_insert(wx_app):
    frame = wx.Frame(None)
    panel = wx.Panel(frame)
    sizer = HelpStaticBox(panel, "lbl", "help", _noop)

    first = wx.TextCtrl(panel)
    sizer.Prepend(first)
    assert sizer.GetItemCount() == 1
    row = sizer.GetItem(0).GetSizer()
    assert row.GetItem(0).GetWindow() is first
    assert isinstance(row.GetItem(1).GetWindow(), wx.Button)

    second = wx.TextCtrl(panel)
    sizer.Prepend(second)
    assert sizer.GetItemCount() == 2
    assert sizer.GetItem(1).GetWindow() is second

    third = wx.TextCtrl(panel)
    sizer.Insert(0, third)
    assert sizer.GetItem(1).GetWindow() is third

    fourth = wx.TextCtrl(panel)
    sizer.Insert(1, fourth)
    assert sizer.GetItem(2).GetWindow() is fourth
    assert sizer.GetItem(3).GetWindow() is second
    assert sizer.GetItemCount() == 4
    panel.Destroy()
    frame.Destroy()
    app = wx.GetApp()
    if app is not None:
        with suppress(Exception):
            app.Yield(True)


def test_calculate_popup_position_prefers_right():
    from app.ui import helpers

    anchor = wx.Rect(100, 100, 40, 20)
    popup = wx.Size(200, 120)
    display = wx.Rect(0, 0, 800, 600)

    x, y = helpers._calculate_popup_position(anchor, popup, display)
    assert (x, y) == (148, 100)


def test_calculate_popup_position_uses_left_when_needed():
    from app.ui import helpers

    anchor = wx.Rect(700, 120, 80, 30)
    popup = wx.Size(200, 100)
    display = wx.Rect(0, 0, 800, 600)

    x, y = helpers._calculate_popup_position(anchor, popup, display)
    assert (x, y) == (492, 120)


def test_calculate_popup_position_falls_back_below():
    from app.ui import helpers

    anchor = wx.Rect(40, 40, 260, 80)
    popup = wx.Size(200, 120)
    display = wx.Rect(0, 0, 320, 600)

    x, y = helpers._calculate_popup_position(anchor, popup, display)
    assert (x, y) == (40, 128)


def test_calculate_popup_position_clamps_to_screen():
    from app.ui import helpers

    anchor = wx.Rect(0, 0, 10, 10)
    popup = wx.Size(300, 260)
    display = wx.Rect(0, 0, 200, 150)

    x, y = helpers._calculate_popup_position(anchor, popup, display)
    assert (x, y) == (8, 8)
