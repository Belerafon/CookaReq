import wx

from app.ui.helpers import HelpStaticBox


def _noop(msg: str) -> None:  # pragma: no cover - placeholder callback
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
    frame.Destroy()
