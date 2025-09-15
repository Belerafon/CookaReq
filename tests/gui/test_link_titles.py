import pytest
import wx

from app.core.model import Priority, Requirement, RequirementType, Status, Verification
from app.ui.editor_panel import EditorPanel

pytestmark = pytest.mark.gui


def test_added_link_shows_id_and_title(wx_app, monkeypatch):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_directory("dummy")

    req = Requirement(
        id=123,
        title="Sample",
        statement="",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="",
        priority=Priority.MEDIUM,
        source="",
        verification=Verification.ANALYSIS,
    )

    panel.derived_id.SetValue("123")
    panel._on_add_link_generic("derived_from")

    assert panel.derived_list.GetItemText(0, 0) == "123"
    assert panel.derived_list.GetItemText(0, 1) == ""
    frame.Destroy()
