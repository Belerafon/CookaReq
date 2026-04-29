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
        {"rid": "HLR1", "title": "High", "document": "High", "prefix": "HLR"},
        {"rid": "SYS2", "title": "System", "document": "System", "prefix": "SYS"},
    ]
    dialog = RequirementLinkPickerDialog(
        frame,
        candidates,
        current_prefix="SYS",
    )
    try:
        # По умолчанию должен быть выбран высокоуровневый список (HLR).
        assert dialog._source_filter_key == "HLR"
        option_labels = [dialog._source_choice.GetString(index) for index in range(dialog._source_choice.GetCount())]
        assert option_labels == ["HLR: High", "SYS: System"]
        visible = [row["rid"] for row in dialog._visible_candidates]
        assert visible == ["HLR1"]
        assert dialog._list_panel.list.GetItemCount() == 1
        assert dialog._list_panel.list.GetItem(0, 1).GetText() == "High"
    finally:
        dialog.Destroy()
        frame.Destroy()


def test_link_picker_switches_between_document_lists(wx_app):
    frame = wx.Frame(None)
    candidates = [
        {"rid": "HLR1", "title": "High", "document": "High", "prefix": "HLR", "distance": 1},
        {"rid": "SYS2", "title": "System", "document": "System", "prefix": "SYS", "distance": 0},
    ]
    dialog = RequirementLinkPickerDialog(frame, candidates, current_prefix="SYS")
    try:
        assert [row["rid"] for row in dialog._visible_candidates] == ["HLR1"]
        dialog._source_choice.SetSelection(1)  # SYS: System
        dialog._on_source_change(wx.CommandEvent(wx.EVT_CHOICE.typeId))
        assert [row["rid"] for row in dialog._visible_candidates] == ["SYS2"]
    finally:
        dialog.Destroy()
        frame.Destroy()


def test_link_picker_shows_requirement_text_tooltip(wx_app):
    frame = wx.Frame(None)
    candidates = [
        {
            "rid": "HLR1",
            "title": "High-level requirement",
            "statement": "Полный текст высокоуровневого требования",
            "document": "High",
            "prefix": "HLR",
        }
    ]
    dialog = RequirementLinkPickerDialog(frame, candidates, current_prefix="SYS")
    try:
        dialog._apply_list_tooltip(0)
        tooltip_obj = dialog._list_panel.list.GetToolTip()
        assert tooltip_obj is not None
        assert tooltip_obj.GetTip() == "Полный текст высокоуровневого требования"
    finally:
        dialog.Destroy()
        frame.Destroy()
