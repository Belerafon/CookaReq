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
        "id": 1,
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
        "id": 1,
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
    assert frame.editor.fields["id"].GetValue() == str(data["id"])

    frame.Destroy()
    app.Destroy()


def _sample_requirement():
    return {
        "id": 1,
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


def _prepare_frame(monkeypatch, tmp_path):
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

    return wx, app, frame


def test_main_frame_clone_requirement_creates_copy(monkeypatch, tmp_path):
    from app.core.store import save

    data = _sample_requirement()
    save(tmp_path, data)

    wx, app, frame = _prepare_frame(monkeypatch, tmp_path)

    frame.on_clone_requirement(frame.model.get_all()[0].id)

    assert frame.editor.IsShown()
    new_id = frame.editor.fields["id"].GetValue()
    assert new_id and new_id != str(data["id"])
    assert frame.editor.fields["title"].GetValue().startswith("(Copy)")
    assert len(frame.model.get_all()) == 2

    frame.Destroy()
    app.Destroy()


def test_main_frame_new_requirement_button(monkeypatch, tmp_path):
    wx, app, frame = _prepare_frame(monkeypatch, tmp_path)

    # emulate toolbar event for new requirement
    evt = wx.CommandEvent(wx.EVT_TOOL.typeId, wx.ID_NEW)
    frame.ProcessEvent(evt)

    assert frame.editor.IsShown()
    assert frame.model.get_all()
    assert frame.editor.fields["id"].GetValue() == str(frame.model.get_all()[0].id)

    frame.Destroy()
    app.Destroy()


def test_main_frame_delete_requirement_removes_file(monkeypatch, tmp_path):
    from app.core.store import save

    data = _sample_requirement()
    path = save(tmp_path, data)

    wx, app, frame = _prepare_frame(monkeypatch, tmp_path)

    assert path.exists()
    assert frame.panel.list.GetItemCount() == 1

    frame.on_delete_requirement(frame.model.get_all()[0].id)

    assert frame.panel.list.GetItemCount() == 0
    assert not path.exists()

    frame.Destroy()
    app.Destroy()
