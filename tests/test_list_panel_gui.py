import pytest


def test_list_panel_real_widgets():
    wx = pytest.importorskip("wx")
    app = wx.App()
    from app.ui.list_panel import ListPanel
    frame = wx.Frame(None)
    panel = ListPanel(frame)

    assert isinstance(panel.search, wx.SearchCtrl)
    assert isinstance(panel.list, wx.ListCtrl)
    assert panel.search.GetParent() is panel
    assert panel.list.GetParent() is panel

    frame.Destroy()
    app.Destroy()
