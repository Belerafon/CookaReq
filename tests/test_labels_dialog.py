import importlib
from types import SimpleNamespace

import pytest

from app.core.labels import Label


def test_labels_dialog_changes_color():
    wx = pytest.importorskip("wx")
    app = wx.App()
    from app.ui.labels_dialog import LabelsDialog

    dlg = LabelsDialog(None, [Label("ui", "#ff0000")])
    dlg.list.Select(0)
    dlg._on_select(SimpleNamespace(GetIndex=lambda: 0))

    class DummyEvent:
        def GetColour(self):
            return wx.Colour("#00ff00")

    dlg._on_color_changed(DummyEvent())
    labels = dlg.get_labels()
    assert labels[0].color.lower() == "#00ff00"
    dlg.Destroy()
    app.Destroy()


def _prepare_frame(monkeypatch, tmp_path):
    from app.core.store import save

    data = {
        "id": 1,
        "title": "Title",
        "statement": "Statement",
        "type": "requirement",
        "status": "draft",
        "owner": "user",
        "priority": "medium",
        "source": "spec",
        "verification": "analysis",
        "labels": ["ui"],
        "revision": 1,
    }
    save(tmp_path, data)

    wx = pytest.importorskip("wx")
    app = wx.App()

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

    import app.ui.list_panel as list_panel
    import app.ui.main_frame as main_frame
    importlib.reload(list_panel)
    importlib.reload(main_frame)

    frame = main_frame.MainFrame(None)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, wx.ID_OPEN)
    frame.ProcessEvent(evt)

    return wx, app, frame, main_frame


def test_main_frame_manage_labels_saves(monkeypatch, tmp_path):
    wx, app, frame, main_frame_mod = _prepare_frame(monkeypatch, tmp_path)

    class DummyLabelsDialog:
        def __init__(self, parent, labels):
            self._labels = [Label(l.name, "#123456") for l in labels]

        def ShowModal(self):
            return wx.ID_OK

        def get_labels(self):
            return self._labels

        def Destroy(self):
            pass

    monkeypatch.setattr(main_frame_mod, "LabelsDialog", DummyLabelsDialog)

    evt = wx.CommandEvent(wx.EVT_MENU.typeId, frame.manage_labels_id)
    frame.ProcessEvent(evt)

    from app.core import store

    labels = store.load_labels(tmp_path)
    assert labels[0].color == "#123456"

    frame.Destroy()
    app.Destroy()
