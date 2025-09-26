import pytest
import wx

from app.core.model import Priority, Requirement, RequirementType, Status, Verification
from app.ui.editor_panel import EditorPanel

pytestmark = pytest.mark.gui


def test_title_column_expands_to_available_width(wx_app, monkeypatch):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_directory("dummy")

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

    frame.SetClientSize((400, 300))
    frame.Show()
    frame.SendSizeEvent()

    panel.links_id.SetValue("SYS1")
    panel._on_add_link_generic("links")

    panel.links_list.SendSizeEvent()
    panel._autosize_link_columns(panel.links_list)

    total = panel.links_list.GetClientSize().width
    id_width = panel.links_list.GetColumnWidth(0)
    title_width = panel.links_list.GetColumnWidth(1)
    assert title_width >= total - id_width - 2
    frame.Destroy()
