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

    def on_clone(req_id: int) -> None:
        called["clone"] = req_id

    def on_delete(req_id: int) -> None:
        called["delete"] = req_id

    panel = list_panel.ListPanel(frame, on_clone=on_clone, on_delete=on_delete)
    panel.set_requirements([{ "id": 1, "title": "T" }])

    menu, clone_item, delete_item, _ = panel._create_context_menu(0, 0)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, clone_item.GetId())
    panel.ProcessEvent(evt)
    menu.Destroy()

    menu, clone_item, delete_item, _ = panel._create_context_menu(0, 0)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, delete_item.GetId())
    panel.ProcessEvent(evt)
    menu.Destroy()

    assert called == {"clone": 1, "delete": 1}

    frame.Destroy()
    app.Destroy()


def test_bulk_edit_updates_selected_items(monkeypatch):
    wx = pytest.importorskip("wx")
    app = wx.App()
    import app.ui.list_panel as list_panel
    importlib.reload(list_panel)
    frame = wx.Frame(None)
    panel = list_panel.ListPanel(frame)
    panel.set_columns(["version", "type"])
    reqs = [
        {"id": 1, "title": "A", "version": "1", "type": "requirement"},
        {"id": 2, "title": "B", "version": "1", "type": "requirement"},
    ]
    panel.set_requirements(reqs)
    panel.list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    panel.list.SetItemState(1, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    monkeypatch.setattr(panel, "_prompt_value", lambda field: "2" if field == "version" else "constraint")
    panel._on_edit_field(1)
    panel._on_edit_field(2)
    assert [r["version"] for r in reqs] == ["2", "2"]
    assert [r["type"] for r in reqs] == ["constraint", "constraint"]
    frame.Destroy()
    app.Destroy()

