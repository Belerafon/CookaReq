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


def test_labels_dialog_adds_presets():
    wx = pytest.importorskip("wx")
    app = wx.App()
    from app.ui.labels_dialog import LabelsDialog
    from app.core.labels import PRESET_SETS

    dlg = LabelsDialog(None, [])
    dlg._on_add_preset_set("basic")
    labels = dlg.get_labels()
    assert {l.name for l in labels} == {l.name for l in PRESET_SETS["basic"]}
    # calling again should not duplicate
    dlg._on_add_preset_set("basic")
    assert len(dlg.get_labels()) == len(PRESET_SETS["basic"])
    dlg.Destroy()
    app.Destroy()


def test_labels_dialog_deletes_selected():
    wx = pytest.importorskip("wx")
    app = wx.App()
    from app.ui.labels_dialog import LabelsDialog

    dlg = LabelsDialog(None, [Label("a", "#111111"), Label("b", "#222222"), Label("c", "#333333")])
    dlg.list.SetItemState(0, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    dlg.list.SetItemState(2, wx.LIST_STATE_SELECTED, wx.LIST_STATE_SELECTED)
    dlg._on_delete_selected(None)
    names = [l.name for l in dlg.get_labels()]
    assert names == ["b"]
    dlg.Destroy()
    app.Destroy()


def test_labels_dialog_clear_all(monkeypatch):
    wx = pytest.importorskip("wx")
    app = wx.App()
    from app.ui.labels_dialog import LabelsDialog

    dlg = LabelsDialog(None, [Label("a", "#111111")])
    monkeypatch.setattr(wx, "MessageBox", lambda *a, **k: wx.YES)
    dlg._on_clear_all(None)
    assert dlg.get_labels() == []
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

    captured: list[tuple[str, list[str]]] = []
    frame.editor.update_labels_list = lambda labels: captured.append(("editor", labels))
    frame.panel.update_labels_list = lambda labels: captured.append(("panel", labels))

    evt = wx.CommandEvent(wx.EVT_MENU.typeId, frame.manage_labels_id)
    frame.ProcessEvent(evt)

    from app.core import store

    labels = store.load_labels(tmp_path)
    assert labels[0].color == "#123456"
    assert ("editor", ["ui"]) in captured
    assert ("panel", ["ui"]) in captured

    frame.Destroy()
    app.Destroy()
