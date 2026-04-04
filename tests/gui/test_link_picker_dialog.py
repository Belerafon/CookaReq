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
