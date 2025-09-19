import importlib

import pytest

from app.core.model import Priority, Requirement, RequirementType, Status, Verification
from app.ui.requirement_model import RequirementModel

REQUIRES_GUI = True


def _req(req_id: int, title: str, **overrides) -> Requirement:
    data = {
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
    data.update(overrides)
    return Requirement(**data)


def test_list_panel_real_widgets(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    panel = list_panel.ListPanel(frame, model=RequirementModel())

    frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
    frame.GetSizer().Add(panel, 1, wx.EXPAND)
    frame.Layout()

    try:
        assert panel in frame.GetChildren()
        assert isinstance(panel.filter_summary, wx.StaticText)
        assert isinstance(panel.list, wx.ListCtrl)
        assert panel.list.GetParent() is panel
        assert panel.filter_summary.GetParent() is panel
        assert panel.list.GetColumnCount() == 1
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_refresh_selects_new_row(wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.list_panel as list_panel

    importlib.reload(list_panel)
    frame = wx.Frame(None)
    panel = list_panel.ListPanel(frame, model=RequirementModel())
    panel.set_columns(["id"])
    panel.set_requirements([
        _req(1, "A"),
        _req(2, "B"),
        _req(3, "C"),
    ])

    try:
        panel.refresh(select_id=3)
        selected = panel.list.GetFirstSelected()
        assert selected != wx.NOT_FOUND
        assert panel.list.GetItemData(selected) == 3
    finally:
        frame.Destroy()
        wx_app.Yield()
