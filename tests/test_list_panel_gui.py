import importlib
import pytest
from app.core.model import (
    Requirement,
    RequirementType,
    Status,
    Priority,
    Verification,
    DerivationLink,
)


def _req(id: int, title: str, **kwargs) -> Requirement:
    base = dict(
        id=id,
        title=title,
        statement="",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="",
        priority=Priority.MEDIUM,
        source="",
        verification=Verification.ANALYSIS,
    )
    base.update(kwargs)
    return Requirement(**base)


def test_list_panel_real_widgets():
    wx = pytest.importorskip("wx")
    app = wx.App()
    import app.ui.list_panel as list_panel
    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel
    panel = list_panel.ListPanel(frame, model=RequirementModel())

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


def test_list_panel_context_menu_calls_handlers(monkeypatch):
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

    from app.ui.requirement_model import RequirementModel
    panel = list_panel.ListPanel(frame, model=RequirementModel(), on_clone=on_clone, on_delete=on_delete)
    panel.set_columns(["version"])
    reqs = [_req(1, "T", version="1")]
    panel.set_requirements(reqs)
    monkeypatch.setattr(panel, "_prompt_value", lambda field: "2")
    panel.list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)

    menu, clone_item, delete_item, edit_item = panel._create_context_menu(0, 0)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, clone_item.GetId())
    menu.ProcessEvent(evt)
    menu.Destroy()

    menu, clone_item, delete_item, edit_item = panel._create_context_menu(0, 0)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, delete_item.GetId())
    menu.ProcessEvent(evt)
    menu.Destroy()

    menu, clone_item, delete_item, edit_item = panel._create_context_menu(0, 1)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, edit_item.GetId())
    menu.ProcessEvent(evt)
    menu.Destroy()

    assert called == {"clone": 1, "delete": 1}
    assert reqs[0].version == "2"

    frame.Destroy()
    app.Destroy()


def test_list_panel_context_menu_via_event(monkeypatch):
    wx = pytest.importorskip("wx")
    app = wx.App()
    import app.ui.list_panel as list_panel
    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel
    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_columns(["version"])
    panel.set_requirements([_req(1, "T", version="1")])
    frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
    frame.GetSizer().Add(panel, 1, wx.EXPAND)
    frame.Layout()
    frame.Show()
    app.Yield()

    called: dict[str, tuple[int, int | None]] = {}

    def fake_popup(index: int, col: int | None) -> None:
        called["args"] = (index, col)

    monkeypatch.setattr(panel, "_popup_context_menu", fake_popup)

    monkeypatch.setattr(panel.list, "HitTestSubItem", lambda pt: (0, 0, 0))
    monkeypatch.setattr(panel.list, "ScreenToClient", lambda pt: pt)
    evt = wx.ContextMenuEvent(wx.EVT_CONTEXT_MENU.typeId, panel.list.GetId())
    evt.SetPosition(wx.Point(0, 0))
    evt.SetEventObject(panel.list)
    panel._on_context_menu(evt)

    assert called.get("args") == (0, 0)
    frame.Destroy()
    app.Destroy()


def test_bulk_edit_updates_selected_items(monkeypatch):
    wx = pytest.importorskip("wx")
    app = wx.App()
    import app.ui.list_panel as list_panel
    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel
    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_columns(["version", "type"])
    reqs = [
        _req(1, "A", version="1", type=RequirementType.REQUIREMENT),
        _req(2, "B", version="1", type=RequirementType.REQUIREMENT),
    ]
    panel.set_requirements(reqs)
    panel.list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    panel.list.SetItemState(1, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    monkeypatch.setattr(
        panel,
        "_prompt_value",
        lambda field: "2" if field == "version" else RequirementType.CONSTRAINT,
    )
    panel._on_edit_field(1)
    panel._on_edit_field(2)
    assert [r.version for r in reqs] == ["2", "2"]
    assert [r.type for r in reqs] == [RequirementType.CONSTRAINT, RequirementType.CONSTRAINT]
    frame.Destroy()
    app.Destroy()


def test_recalc_derived_map_updates_count():
    wx = pytest.importorskip("wx")
    app = wx.App()
    import app.ui.list_panel as list_panel
    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel
    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_columns(["derived_count"])
    req1 = _req(1, "S")
    req2 = _req(2, "D", derived_from=[DerivationLink(source_id=1, source_revision=1, suspect=False)])
    panel.set_requirements([req1, req2])
    assert panel.list.GetItemText(0, 1) == "1"
    req2.derived_from = []
    panel.recalc_derived_map([req1, req2])
    assert panel.list.GetItemText(0, 1) == "0"
    frame.Destroy()
    app.Destroy()
