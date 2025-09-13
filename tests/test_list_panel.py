"""Tests for DataView-based requirement list panel using real wx."""

import importlib
import pytest

from app.core.model import Requirement, RequirementType, Status, Priority, Verification
from app.core.labels import Label

wx = pytest.importorskip("wx")
dv = pytest.importorskip("wx.dataview")


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


@pytest.fixture
def panel(wx_app):
    import app.ui.list_panel as list_panel
    importlib.reload(list_panel)
    from app.ui.requirement_model import RequirementModel
    frame = wx.Frame(None)
    pnl = list_panel.ListPanel(frame, model=RequirementModel())
    yield pnl
    frame.Destroy()


def test_list_panel_has_filter_and_list(panel):
    import app.ui.list_panel as list_panel
    assert isinstance(panel.filter_btn, wx.Button)
    assert isinstance(panel.list, dv.DataViewCtrl)
    assert panel.filter_btn.GetParent() is panel
    assert panel.list.GetParent() is panel


def test_sort_and_sort_callback(wx_app):
    import app.ui.list_panel as list_panel
    from app.ui.requirement_model import RequirementModel
    calls: list[tuple[int, bool]] = []
    frame = wx.Frame(None)
    pnl = list_panel.ListPanel(frame, model=RequirementModel(), on_sort_changed=lambda c, a: calls.append((c, a)))
    pnl.set_columns(["id"])
    pnl.set_requirements([_req(2, "B"), _req(1, "A")])
    pnl.sort(1, True)
    assert [r.id for r in pnl.model.get_visible()] == [1, 2]
    pnl.sort(1, False)
    assert [r.id for r in pnl.model.get_visible()] == [2, 1]
    assert calls[-1] == (1, False)
    frame.Destroy()


def test_search_and_label_filters(panel):
    panel.set_requirements([
        _req(1, "Login", labels=["ui"]),
        _req(2, "Export", labels=["report"]),
    ])
    panel.set_label_filter(["ui"])
    assert [r.id for r in panel.model.get_visible()] == [1]
    panel.set_label_filter([])
    panel.set_search_query("Export", fields=["title"])
    assert [r.id for r in panel.model.get_visible()] == [2]
    panel.set_label_filter(["ui"])
    panel.set_search_query("Export", fields=["title"])
    assert panel.model.get_visible() == []


def test_apply_filters(panel):
    panel.set_requirements([
        _req(1, "Login", labels=["ui"], owner="alice"),
        _req(2, "Export", labels=["report"], owner="bob"),
    ])
    panel.apply_filters({"labels": ["ui"]})
    assert [r.id for r in panel.model.get_visible()] == [1]
    panel.apply_filters({"labels": [], "field_queries": {"owner": "bob"}})
    assert [r.id for r in panel.model.get_visible()] == [2]


def test_apply_status_filter(panel):
    panel.set_requirements([
        _req(1, "A", status=Status.DRAFT),
        _req(2, "B", status=Status.APPROVED),
    ])
    panel.apply_filters({"status": "approved"})
    assert [r.id for r in panel.model.get_visible()] == [2]
    panel.apply_filters({"status": None})
    assert [r.id for r in panel.model.get_visible()] == [1, 2]


def test_labels_column_uses_renderer(panel):
    import app.ui.list_panel as list_panel
    panel.update_labels_list([Label("ui", "#123456")])
    panel.set_columns(["labels"])
    column = panel.list.GetColumn(1)
    assert isinstance(column.GetRenderer(), list_panel.LabelBadgeRenderer)


def test_sort_by_multiple_labels(panel):
    panel.set_columns(["labels"])
    panel.set_requirements([
        _req(1, "A", labels=["alpha", "zeta"]),
        _req(2, "B", labels=["alpha", "beta"]),
    ])
    panel.sort(1, True)
    assert [r.id for r in panel.model.get_visible()] == [2, 1]


def test_bulk_edit_updates_requirements(monkeypatch, panel):
    panel.set_columns(["version"])
    reqs = [_req(1, "A", version="1"), _req(2, "B", version="1")]
    panel.set_requirements(reqs)
    monkeypatch.setattr(panel, "_get_selected_indices", lambda: [0, 1])
    monkeypatch.setattr(panel, "_prompt_value", lambda field: "2")
    panel._on_edit_field(1)
    assert [r.version for r in reqs] == ["2", "2"]


def test_create_context_menu(panel):
    called = {}
    panel.set_columns(["version"])
    panel.set_requirements([_req(1, "T", version="1")])
    panel.set_handlers(on_clone=lambda i: called.setdefault("clone", i), on_delete=lambda i: called.setdefault("delete", i))
    menu, clone_item, delete_item, edit_item = panel._create_context_menu(0, 1)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, clone_item.GetId())
    menu.ProcessEvent(evt)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, delete_item.GetId())
    menu.ProcessEvent(evt)
    menu.Destroy()
    assert called == {"clone": 1, "delete": 1}

