"""Tests for list panel gui."""

import importlib
import logging

import pytest

from app.core.model import (
    Link,
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
)

pytestmark = pytest.mark.gui


def _req(req_id: int, title: str, **kwargs) -> Requirement:
    base = {
        "id": req_id,
        "title": title,
        "statement": "",
        "type": RequirementType.REQUIREMENT,
        "status": Status.DRAFT,
        "owner": "",
        "priority": Priority.MEDIUM,
        "source": "",
        "verification": Verification.ANALYSIS,
    }
    base.update(kwargs)
    return Requirement(**base)


def test_list_panel_real_widgets(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(frame, model=RequirementModel())

    frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
    frame.GetSizer().Add(panel, 1, wx.EXPAND)
    frame.Layout()

    assert panel in frame.GetChildren()
    assert isinstance(panel.filter_btn, wx.Button)
    assert isinstance(panel.reset_btn, wx.BitmapButton)
    assert isinstance(panel.list, wx.ListCtrl)
    assert panel.filter_btn.GetParent() is panel
    assert panel.reset_btn.GetParent() is panel
    assert panel.list.GetParent() is panel
    assert panel.filter_btn.IsShown()
    assert panel.list.IsShown()
    assert not panel.reset_btn.IsShown()

    frame.Destroy()


def test_reset_button_visibility_gui(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_search_query("T")
    wx_app.Yield()
    assert panel.reset_btn.IsShown()
    panel.reset_filters()
    wx_app.Yield()
    assert not panel.reset_btn.IsShown()
    frame.Destroy()


def test_list_panel_debug_level_text_labels(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(frame, model=RequirementModel(), debug_level=2)
    panel.set_columns(["labels"])
    panel.set_requirements([_req(1, "Item", labels=["bug", "feature"])])
    wx_app.Yield()

    assert panel.debug.label_bitmaps is False
    assert panel.list.GetColumnCount() >= 2
    assert panel.list.GetItemText(0) == "bug, feature"
    assert panel.list.GetItemText(0, 1) == "Item"

    frame.Destroy()


def test_list_panel_debug_level_plain_list_ctrl(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(frame, model=RequirementModel(), debug_level=18)
    panel.set_columns(["labels", "status"])
    panel.set_requirements([_req(1, "Plain", labels=["bug"], status=Status.APPROVED)])
    wx_app.Yield()

    assert panel.filter_btn is None
    assert panel.reset_btn is None
    assert panel.filter_summary is None
    assert panel.list.GetColumnCount() == 1
    assert panel.list.GetItemText(0) == "Plain"
    assert panel.debug.context_menu is False
    assert panel.debug.rich_rendering is False
    assert panel.debug.subitem_images is False
    assert panel.debug.sorter_mixin is False
    assert panel.debug.documents_integration is False
    assert panel.debug.callbacks is False
    assert panel.debug.selection_events is False
    assert panel.debug.model_driven is False

    frame.Destroy()


def test_list_panel_debug_level_logs_disabled_features(wx_app, caplog):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel

    caplog.set_level(logging.INFO, logger="cookareq")

    panel = list_panel.ListPanel(frame, model=RequirementModel(), debug_level=16)
    panel.set_requirements([_req(1, "Item")])
    wx_app.Yield()

    message = caplog.text
    assert f"ListPanel debug level {panel.debug_level}" in message
    assert "background inheritance" in message
    assert "documents integration" in message
    assert "action callbacks" in message

    frame.Destroy()


def test_main_frame_plain_mode_skips_selection_binding(monkeypatch, tmp_path, wx_app):
    wx = pytest.importorskip("wx")

    from app.config import ConfigManager
    from app.settings import MAX_LIST_PANEL_DEBUG_LEVEL
    import app.ui.main_frame as main_frame

    calls: list[tuple[object, object]] = []

    original_bind = wx.Window.Bind

    def recording_bind(self, event, handler=None, source=None, id=wx.ID_ANY, id2=wx.ID_ANY):
        calls.append((self, event))
        return original_bind(self, event, handler, source=source, id=id, id2=id2)

    monkeypatch.setattr(wx.Window, "Bind", recording_bind)

    config = ConfigManager(app_name="TestCookaReq", path=tmp_path / "cfg.ini")
    config.set_list_panel_debug_level(MAX_LIST_PANEL_DEBUG_LEVEL)

    frame = main_frame.MainFrame(None, config=config)

    list_ctrl = frame.panel.list
    bound_events = [event for target, event in calls if target is list_ctrl]

    assert wx.EVT_LIST_ITEM_SELECTED not in bound_events
    assert wx.EVT_LIST_ITEM_ACTIVATED not in bound_events

    frame.Destroy()


def test_list_panel_context_menu_calls_handlers(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    called: dict[str, int] = {}

    def on_clone(req_id: int) -> None:
        called["clone"] = req_id

    def on_delete(req_id: int) -> None:
        called["delete"] = req_id

    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(
        frame,
        model=RequirementModel(),
        on_clone=on_clone,
        on_delete=on_delete,
    )
    panel.set_columns(["revision"])
    reqs = [_req(1, "T", revision=1)]
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
    assert reqs[0].revision == 2

    frame.Destroy()


def test_list_panel_delete_many_uses_batch_handler(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    called: dict[str, object] = {}

    def on_delete_many(req_ids):
        called["many"] = list(req_ids)

    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(
        frame,
        model=RequirementModel(),
        on_delete_many=on_delete_many,
    )
    panel.set_columns(["revision"])
    panel.set_requirements([_req(1, "A", revision=1), _req(2, "B", revision=1)])
    panel.list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    panel.list.SetItemState(1, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)

    menu, clone_item, delete_item, edit_item = panel._create_context_menu(0, 0)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, delete_item.GetId())
    menu.ProcessEvent(evt)
    menu.Destroy()

    assert called["many"] == [1, 2]
    frame.Destroy()


def test_list_panel_delete_many_falls_back_to_single_handler(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    called: list[int] = []

    def on_delete(req_id: int) -> None:
        called.append(req_id)

    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(
        frame,
        model=RequirementModel(),
        on_delete=on_delete,
    )
    panel.set_columns(["revision"])
    panel.set_requirements([_req(1, "A", revision=1), _req(2, "B", revision=1)])
    panel.list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    panel.list.SetItemState(1, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)

    menu, clone_item, delete_item, edit_item = panel._create_context_menu(0, 0)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, delete_item.GetId())
    menu.ProcessEvent(evt)
    menu.Destroy()

    assert called == [1, 2]
    frame.Destroy()


def test_list_panel_refresh_selects_new_row(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_columns(["id", "title"])
    panel.set_requirements([
        _req(1, "A"),
        _req(2, "B"),
        _req(3, "C"),
    ])
    wx_app.Yield()

    panel.refresh(select_id=3)
    wx_app.Yield()

    selected = panel.list.GetFirstSelected()
    assert selected != wx.NOT_FOUND
    assert panel.list.GetItemData(selected) == 3

    frame.Destroy()


def test_context_menu_hides_single_item_actions(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_columns(["title"])
    panel.set_requirements([
        _req(1, "A"),
        _req(2, "B"),
    ])
    panel.list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    panel.list.SetItemState(1, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)

    menu, clone_item, delete_item, edit_item = panel._create_context_menu(0, 0)
    labels = [item.GetItemLabelText() for item in menu.GetMenuItems()]
    assert "Clone" not in labels
    assert "Derive" not in labels
    assert clone_item is None
    menu.Destroy()
    frame.Destroy()


def test_list_panel_context_menu_via_event(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_columns(["revision"])
    panel.set_requirements([_req(1, "T", revision=1)])
    frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
    frame.GetSizer().Add(panel, 1, wx.EXPAND)
    frame.Layout()
    frame.Show()
    wx_app.Yield()

    called: dict[str, tuple[int, int | None]] = {}

    def fake_popup(index: int, col: int | None) -> None:
        called["args"] = (index, col)

    monkeypatch.setattr(panel, "_popup_context_menu", fake_popup)

    monkeypatch.setattr(panel.list, "HitTest", lambda pt: (0, 0))
    monkeypatch.setattr(panel.list, "ScreenToClient", lambda pt: pt)
    evt = wx.ContextMenuEvent(wx.EVT_CONTEXT_MENU.typeId, panel.list.GetId())
    evt.SetPosition(wx.Point(0, 0))
    evt.SetEventObject(panel.list)
    panel._on_context_menu(evt)

    assert called.get("args") == (0, None)
    frame.Destroy()


def test_bulk_edit_updates_selected_items(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_columns(["revision", "type"])
    reqs = [
        _req(1, "A", revision=1, type=RequirementType.REQUIREMENT),
        _req(2, "B", revision=1, type=RequirementType.REQUIREMENT),
    ]
    panel.set_requirements(reqs)
    panel.list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    panel.list.SetItemState(1, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    monkeypatch.setattr(
        panel,
        "_prompt_value",
        lambda field: "2" if field == "revision" else RequirementType.CONSTRAINT,
    )
    panel._on_edit_field(1)
    panel._on_edit_field(2)
    assert [r.revision for r in reqs] == [2, 2]
    assert [r.type for r in reqs] == [
        RequirementType.CONSTRAINT,
        RequirementType.CONSTRAINT,
    ]
    frame.Destroy()


def test_recalc_derived_map_updates_count(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_columns(["derived_count"])
    req1 = _req(1, "S")
    req2 = _req(2, "D", links=["1"])
    panel.set_requirements([req1, req2])
    assert panel.list.GetItem(0, 1).GetText() == "1"
    req2.links = []
    panel.recalc_derived_map([req1, req2])
    assert panel.list.GetItem(0, 1).GetText() == "0"
    frame.Destroy()


def test_derived_column_and_marker(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_columns(["derived_from"])
    parent = _req(1, "Parent", doc_prefix="REQ", rid="REQ-001")
    child = _req(2, "Child", doc_prefix="REQ", rid="REQ-002", links=[Link(rid="REQ-001")])
    panel.set_requirements([parent, child])

    assert panel.list.GetItemText(1, 0).startswith("↳")
    assert panel.list.GetItemText(1, 1) == "REQ-001 — Parent"
    frame.Destroy()


def test_reorder_columns_gui(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_columns(["id", "status"])
    panel.reorder_columns(1, 2)
    assert panel.columns == ["status", "id"]
    assert panel.list.GetColumn(1).GetText() == list_panel.locale.field_label("status")
    frame.Destroy()
