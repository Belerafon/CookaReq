import importlib
import pytest


def test_list_panel_real_widgets():
    wx = pytest.importorskip("wx")
    app = wx.App()
    import app.ui.list_panel as list_panel
    importlib.reload(list_panel)
    frame = wx.Frame(None)
    panel = list_panel.ListPanel(frame)

    assert isinstance(panel.search, wx.SearchCtrl)
    assert isinstance(panel.list, wx.ListCtrl)
    assert panel.search.GetParent() is panel
    assert panel.list.GetParent() is panel

    frame.Destroy()
    app.Destroy()
