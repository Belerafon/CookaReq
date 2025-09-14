import wx
from app.ui.editor_panel import EditorPanel
from app.core.model import Requirement, RequirementType, Status, Priority, Verification
from app.core import requirements as req_ops
import pytest

pytestmark = pytest.mark.gui


def test_title_column_expands_to_available_width(wx_app, monkeypatch):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_directory('dummy')

    req = Requirement(
        id=1,
        title="T",
        statement="",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="",
        priority=Priority.MEDIUM,
        source="",
        verification=Verification.ANALYSIS,
    )
    monkeypatch.setattr(req_ops, 'get_requirement', lambda d, i: req)

    frame.SetClientSize((400, 300))
    frame.Show()
    wx.GetApp().Yield()

    panel.derived_id.SetValue('1')
    panel._on_add_link_generic('derived_from')

    panel.derived_list.SendSizeEvent()
    wx.GetApp().Yield()

    total = panel.derived_list.GetClientSize().width
    id_width = panel.derived_list.GetColumnWidth(0)
    title_width = panel.derived_list.GetColumnWidth(1)
    assert title_width >= total - id_width - 2
    frame.Destroy()
