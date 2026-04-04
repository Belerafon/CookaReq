import pytest
import wx

from app.ui.editor_panel import RequirementLinkPickerDialog

pytestmark = pytest.mark.gui


def test_link_picker_persists_window_geometry(wx_app):
    original_config = wx.Config.Get()
    config = wx.Config("CookaReqTestLinkPicker")
    wx.Config.Set(config)
    try:
        frame = wx.Frame(None)
        candidates = [{"rid": "SYS1", "title": "Title", "document": "System"}]

        dialog = RequirementLinkPickerDialog(frame, candidates, selected_rids={"SYS1"})
        dialog.SetSize((980, 700))
        dialog.SetPosition((120, 140))
        dialog.Destroy()

        restored = RequirementLinkPickerDialog(frame, candidates, selected_rids={"SYS1"})
        width, height = restored.GetSize()
        x, y = restored.GetPosition()
        assert width == 980
        assert height == 700
        assert x == 120
        assert y == 140
        restored.Destroy()
        frame.Destroy()
    finally:
        wx.Config.Set(original_config)


def test_link_picker_defaults_to_high_level_scope(wx_app):
    frame = wx.Frame(None)
    candidates = [
        {"rid": "HLR1", "title": "High", "document": "High", "prefix": "HLR", "scope": "HLR — High"},
        {"rid": "SYS2", "title": "System", "document": "System", "prefix": "SYS", "scope": "SYS — System"},
    ]
    dialog = RequirementLinkPickerDialog(frame, candidates, current_prefix="SYS")
    try:
        # По умолчанию должен быть выбран high-level scope.
        assert dialog._source_filter_key == "high"
        option_labels = [dialog._source_choice.GetString(index) for index in range(dialog._source_choice.GetCount())]
        assert option_labels == [
            "Higher-level requirements",
            "Current document requirements",
            "All allowed requirements",
        ]
        visible = [row["rid"] for row in dialog._visible_candidates]
        assert visible == ["HLR1"]
        assert "HLR — High" in dialog._checklist.GetString(0)
    finally:
        dialog.Destroy()
        frame.Destroy()
