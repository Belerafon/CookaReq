"""Tests for list panel gui."""

import importlib

import pytest

from app.core.model import (
    Link,
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
    requirement_to_dict,
)
from app.services.requirements import RequirementsService
from app.ui.controllers import DocumentsController

pytestmark = [pytest.mark.gui, pytest.mark.gui_smoke]


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
    assert panel.reset_btn.IsShown()
    panel.reset_filters()
    assert not panel.reset_btn.IsShown()
    frame.Destroy()


def _flush_events(wx, count: int = 5) -> None:
    for _ in range(count):
        wx.Yield()


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


def test_marquee_selection_starts_from_cell(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    frame.SetSizer(wx.BoxSizer(wx.VERTICAL))

    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(frame, model=RequirementModel())
    frame.GetSizer().Add(panel, 1, wx.EXPAND)
    panel.set_requirements([_req(i, f"Req {i}") for i in range(1, 6)])

    frame.SetSize((600, 400))
    frame.Show()
    panel.list.SetFocus()
    _flush_events(wx)

    list_ctrl = panel.list
    first_rect = list_ctrl.GetItemRect(0)
    third_rect = list_ctrl.GetItemRect(2)
    start = first_rect.GetTopLeft()
    start = wx.Point(start.x + max(first_rect.GetWidth() // 4, 4), start.y + first_rect.GetHeight() // 2)
    end = third_rect.GetTopLeft()
    end = wx.Point(end.x + max(third_rect.GetWidth() // 2, 10), end.y + third_rect.GetHeight() - 2)

    sim = wx.UIActionSimulator()
    screen_start = list_ctrl.ClientToScreen(start)
    screen_end = list_ctrl.ClientToScreen(end)

    sim.MouseMove(screen_start.x, screen_start.y)
    _flush_events(wx)
    sim.MouseDown(wx.MOUSE_BTN_LEFT)
    _flush_events(wx)
    sim.MouseMove(screen_end.x, screen_end.y)
    _flush_events(wx, count=10)
    sim.MouseUp(wx.MOUSE_BTN_LEFT)
    _flush_events(wx, count=6)

    assert panel.get_selected_ids() == [1, 2, 3]

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


def test_list_panel_bulk_status_change(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel
    from app.ui import locale as ui_locale

    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_columns(["status"])
    panel.set_requirements([
        _req(1, "A", status=Status.DRAFT),
        _req(2, "B", status=Status.IN_REVIEW),
    ])
    panel.list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    panel.list.SetItemState(1, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)

    menu, _, delete_item, edit_item = panel._create_context_menu(0, 0)
    assert delete_item is not None
    assert edit_item is None
    status_menu_item = next(
        (item for item in menu.GetMenuItems() if item.GetSubMenu()),
        None,
    )
    assert status_menu_item is not None
    assert status_menu_item.GetItemLabelText() == list_panel._("Set status for selected")
    status_menu = status_menu_item.GetSubMenu()
    target_label = ui_locale.code_to_label("status", Status.APPROVED.value)
    approved_item = next(
        (item for item in status_menu.GetMenuItems() if item.GetItemLabel() == target_label),
        None,
    )
    assert approved_item is not None

    evt = wx.CommandEvent(wx.EVT_MENU.typeId, approved_item.GetId())
    status_menu.ProcessEvent(evt)
    menu.Destroy()

    assert panel.model.get_by_id(1).status is Status.APPROVED
    assert panel.model.get_by_id(2).status is Status.APPROVED
    assert panel.get_selected_ids() == [1, 2]
    status_col = panel._field_order.index("status")
    assert panel.list.GetItemText(0, status_col) == target_label
    assert panel.list.GetItemText(1, status_col) == target_label

    frame.Destroy()


def test_list_panel_bulk_labels_change(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel
    from app.services.requirements import LabelDef

    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.update_labels_list(
        [
            LabelDef("backend", "Backend", "#123456"),
            LabelDef("api", "API", "#abcdef"),
        ],
        allow_freeform=True,
    )
    panel.set_requirements(
        [
            _req(1, "A", labels=["backend", "legacy"]),
            _req(2, "B", labels=["backend", "api"]),
        ]
    )
    panel.list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    panel.list.SetItemState(1, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)

    captured: dict[str, object] = {}

    class DummyDialog:
        def __init__(self, parent, labels, selected, allow_freeform):
            captured["labels"] = labels
            captured["selected"] = selected
            captured["allow_freeform"] = allow_freeform

        def ShowModal(self):
            return wx.ID_OK

        def Destroy(self):
            captured["destroyed"] = True

        def get_selected(self):
            return ["backend", "ux"]

    monkeypatch.setattr(list_panel, "LabelSelectionDialog", DummyDialog)

    menu, _, delete_item, edit_item = panel._create_context_menu(0, 0)
    assert delete_item is not None
    assert edit_item is None
    labels_item = next(
        (
            item
            for item in menu.GetMenuItems()
            if item.GetItemLabelText() == list_panel._("Set labels…")
        ),
        None,
    )
    assert labels_item is not None

    evt = wx.CommandEvent(wx.EVT_MENU.typeId, labels_item.GetId())
    menu.ProcessEvent(evt)
    menu.Destroy()

    assert captured["allow_freeform"] is True
    available = {label.key for label in captured["labels"]}
    assert {"backend", "api", "legacy"}.issubset(available)
    assert captured["selected"] == ["backend"]
    assert captured.get("destroyed") is True

    assert panel.model.get_by_id(1).labels == ["backend", "ux"]
    assert panel.model.get_by_id(2).labels == ["backend", "ux"]
    assert panel.get_selected_ids() == [1, 2]

    frame.Destroy()


def test_list_panel_single_selection_status_menu(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    from app.ui.requirement_model import RequirementModel

    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_columns(["status"])
    panel.set_requirements([
        _req(1, "A", status=Status.IN_REVIEW),
    ])
    panel.list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)

    menu, _, delete_item, edit_item = panel._create_context_menu(0, 0)
    assert delete_item is not None
    assert edit_item is None

    status_menu_item = next(
        (item for item in menu.GetMenuItems() if item.GetSubMenu()),
        None,
    )
    assert status_menu_item is not None
    assert status_menu_item.GetItemLabelText() == list_panel._("Set status")

    menu.Destroy()
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

    panel.refresh(select_id=3)

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


def test_reload_marks_child_suspect_after_parent_change(wx_app, tmp_path):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    from app.ui.requirement_model import RequirementModel

    service = RequirementsService(tmp_path)
    service.create_document(prefix="SYS", title="System")
    service.create_document(prefix="REQ", title="Requirements", parent="SYS")
    service.create_requirement("SYS", requirement_to_dict(_req(1, "Parent")))
    service.create_requirement(
        "REQ",
        requirement_to_dict(_req(1, "Child", links=["SYS1"])),
    )

    model = RequirementModel()
    controller = DocumentsController(service, model)
    controller.load_documents()
    derived_map = controller.load_items("REQ")

    frame = wx.Frame(None)
    panel = list_panel.ListPanel(frame, model=model)
    panel.set_requirements(model.get_all(), derived_map)

    child = panel.model.get_all()[0]
    assert child.links and child.links[0].suspect is False

    service.update_requirement_field("SYS1", field="statement", value="Updated body")
    derived_map = controller.load_items("REQ")
    panel.set_requirements(model.get_all(), derived_map)

    child = panel.model.get_all()[0]
    assert child.links and child.links[0].suspect is True
    assert panel.derived_map.get("SYS1") == [child.id]

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
