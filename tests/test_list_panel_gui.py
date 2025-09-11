import importlib
import pytest


def test_list_panel_real_widgets():
    wx = pytest.importorskip("wx")
    app = wx.App()
    import app.ui.list_panel as list_panel
    importlib.reload(list_panel)
    frame = wx.Frame(None)
    panel = list_panel.ListPanel(frame)

    frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
    frame.GetSizer().Add(panel, 1, wx.EXPAND)
    frame.Layout()

    assert panel in frame.GetChildren()
    assert isinstance(panel.search, wx.SearchCtrl)
    assert isinstance(panel.list, wx.ListCtrl)
    assert panel.search.GetParent() is panel
    assert panel.list.GetParent() is panel
    assert panel.search.IsShown()
    assert panel.list.IsShown()

    frame.Destroy()
    app.Destroy()


def test_list_panel_context_menu_calls_handlers():
    wx = pytest.importorskip("wx")
    app = wx.App()
    import app.ui.list_panel as list_panel
    importlib.reload(list_panel)
    frame = wx.Frame(None)
    called: dict[str, int] = {}

    def on_clone(idx: int) -> None:
        called["clone"] = idx

    def on_delete(idx: int) -> None:
        called["delete"] = idx

    panel = list_panel.ListPanel(frame, on_clone=on_clone, on_delete=on_delete)
    panel.set_requirements([{"id": "1", "title": "T"}])

    menu, clone_item, delete_item = panel._create_context_menu(0)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, clone_item.GetId())
    panel.ProcessEvent(evt)
    menu.Destroy()

    menu, clone_item, delete_item = panel._create_context_menu(0)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, delete_item.GetId())
    panel.ProcessEvent(evt)
    menu.Destroy()

    assert called == {"clone": 0, "delete": 0}

    frame.Destroy()
    app.Destroy()

