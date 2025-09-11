import importlib
import pytest


def test_main_frame_open_folder(monkeypatch, tmp_path):
    wx = pytest.importorskip("wx")
    app = wx.App()

    called = {}

    class DummyDirDialog:
        def __init__(self, parent, message):
            called["init"] = True
        def ShowModal(self):
            called["show"] = True
            return wx.ID_OK
        def GetPath(self):
            return str(tmp_path)
        def Destroy(self):
            called["destroy"] = True

    monkeypatch.setattr(wx, "DirDialog", DummyDirDialog)

    import app.ui.list_panel as list_panel
    import app.ui.main_frame as main_frame
    importlib.reload(list_panel)
    importlib.reload(main_frame)

    frame = main_frame.MainFrame(None)

    # emulate menu event
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, wx.ID_OPEN)
    frame.ProcessEvent(evt)

    assert called == {"init": True, "show": True, "destroy": True}
    assert isinstance(frame.panel, list_panel.ListPanel)

    frame.Destroy()
    app.Destroy()


def test_main_frame_open_folder_toolbar(monkeypatch, tmp_path):
    wx = pytest.importorskip("wx")
    app = wx.App()

    called = {}

    class DummyDirDialog:
        def __init__(self, parent, message):
            called["init"] = True

        def ShowModal(self):
            called["show"] = True
            return wx.ID_OK

        def GetPath(self):
            return str(tmp_path)

        def Destroy(self):
            called["destroy"] = True

    monkeypatch.setattr(wx, "DirDialog", DummyDirDialog)

    import app.ui.list_panel as list_panel
    import app.ui.main_frame as main_frame
    importlib.reload(list_panel)
    importlib.reload(main_frame)

    frame = main_frame.MainFrame(None)

    # emulate toolbar event
    evt = wx.CommandEvent(wx.EVT_TOOL.typeId, wx.ID_OPEN)
    frame.ProcessEvent(evt)

    assert called == {"init": True, "show": True, "destroy": True}
    assert isinstance(frame.panel, list_panel.ListPanel)

    frame.Destroy()
    app.Destroy()


def test_main_frame_loads_requirements(monkeypatch, tmp_path):
    wx = pytest.importorskip("wx")
    from app.core.store import save

    data = {
        "id": "REQ-1",
        "title": "Title",
        "statement": "Statement",
        "type": "requirement",
        "status": "draft",
        "owner": "user",
        "priority": "medium",
        "source": "spec",
        "verification": "analysis",
        "revision": 1,
    }
    save(tmp_path, data)

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

    assert frame.panel.list.GetItemCount() == 1
    assert frame.panel.list.GetItemText(0) == data["title"]

    frame.Destroy()
    app.Destroy()


def test_main_frame_select_opens_editor(monkeypatch, tmp_path):
    wx = pytest.importorskip("wx")
    from app.core.store import save
    import importlib

    data = {
        "id": "REQ-1",
        "title": "Title",
        "statement": "Statement",
        "type": "requirement",
        "status": "draft",
        "owner": "user",
        "priority": "medium",
        "source": "spec",
        "verification": "analysis",
        "revision": 1,
    }
    save(tmp_path, data)

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

    list_ctrl = frame.panel.list
    list_ctrl.Select(0)
    app.Yield()

    assert frame.editor.IsShown()
    assert frame.editor.fields["id"].GetValue() == data["id"]

    frame.Destroy()
    app.Destroy()
