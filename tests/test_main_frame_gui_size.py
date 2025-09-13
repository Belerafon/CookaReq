"""Tests for main frame gui size."""

import pytest

from app.core.store import save
from app.ui import main_frame


def test_main_frame_editor_multiline_fields_have_size(tmp_path, monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    data = {
        "id": 1,
        "title": "Title",
        "statement": "Stmt",
        "acceptance": "A",
        "conditions": "C",
        "trace_up": "TU",
        "trace_down": "TD",
        "source": "Src",
        "type": "requirement",
        "status": "draft",
        "owner": "Own",
        "priority": "medium",
        "verification": "analysis",
        "revision": 1,
    }
    save(tmp_path, data)

    class DummyDirDialog:
        def __init__(self, parent, message):
            pass

        def ShowModal(self):
            return wx.ID_OK

        def GetPath(self):
            return str(tmp_path)

        def Destroy(self):
            pass

    monkeypatch.setattr(wx, "DirDialog", DummyDirDialog)

    frame = main_frame.MainFrame(None)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, wx.ID_OPEN)
    frame.ProcessEvent(evt)
    frame.Show()
    frame.panel.list.Select(0)
    wx_app.Yield()

    for name in ["statement", "acceptance", "conditions", "trace_up", "trace_down", "source"]:
        assert frame.editor.fields[name].GetSize().GetHeight() > 0

    frame.Destroy()
