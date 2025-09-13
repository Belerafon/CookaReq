import importlib
import pytest
import logging


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


def test_main_frame_run_command_menu(monkeypatch):
    wx = pytest.importorskip("wx")
    app = wx.App()

    called = {}

    class DummyDialog:
        def __init__(self, parent, *, agent, history_path=None):
            called["init"] = True
        def ShowModal(self):
            called["show"] = True
        def Destroy(self):
            called["destroy"] = True

    class DummyAgent:
        def __init__(self, settings, confirm):
            called["agent"] = True

    import app.ui.main_frame as main_frame
    importlib.reload(main_frame)
    monkeypatch.setattr(main_frame, "CommandDialog", DummyDialog)
    monkeypatch.setattr(main_frame, "LocalAgent", DummyAgent)

    frame = main_frame.MainFrame(None)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, frame.navigation.run_command_id)
    frame.ProcessEvent(evt)

    assert called == {"agent": True, "init": True, "show": True, "destroy": True}
    frame.Destroy()
    app.Destroy()


def test_main_frame_run_command_history_persists(monkeypatch, tmp_path):
    wx = pytest.importorskip("wx")
    app = wx.App()
    import importlib
    import json

    import app.ui.command_dialog as cmd
    importlib.reload(cmd)
    history_file = tmp_path / "history.json"
    monkeypatch.setattr(cmd, "_default_history_path", lambda: history_file)

    class DummyAgent:
        def __init__(self, settings=None, confirm=None):
            pass
        def run_command(self, text):
            return {"ok": 1}

    class AutoDialog(cmd.CommandDialog):
        def ShowModal(self):
            self.input.SetValue("cmd")
            self._on_run(None)
            return wx.ID_OK

    import app.ui.main_frame as main_frame
    importlib.reload(main_frame)
    monkeypatch.setattr(main_frame, "LocalAgent", DummyAgent)
    monkeypatch.setattr(main_frame, "CommandDialog", AutoDialog)

    frame = main_frame.MainFrame(None)
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, frame.navigation.run_command_id)
    frame.ProcessEvent(evt)
    evt2 = wx.CommandEvent(wx.EVT_MENU.typeId, frame.navigation.run_command_id)
    frame.ProcessEvent(evt2)

    data = json.loads(history_file.read_text())
    assert len(data) == 2
    assert data[0]["command"] == "cmd"

    frame.Destroy()
    app.Destroy()


def test_log_handler_not_duplicated(tmp_path):
    wx = pytest.importorskip("wx")
    app = wx.App()

    import app.ui.main_frame as main_frame

    logger = logging.getLogger("cookareq")
    for h in list(logger.handlers):
        if isinstance(h, main_frame.WxLogHandler):
            logger.removeHandler(h)

    frame1 = main_frame.MainFrame(None)
    assert (
        sum(isinstance(h, main_frame.WxLogHandler) for h in logger.handlers) == 1
    )
    frame1.Close()
    app.Yield()
    assert (
        sum(isinstance(h, main_frame.WxLogHandler) for h in logger.handlers) == 0
    )

    frame2 = main_frame.MainFrame(None)
    assert (
        sum(isinstance(h, main_frame.WxLogHandler) for h in logger.handlers) == 1
    )
    frame2.Close()
    app.Yield()
    assert (
        sum(isinstance(h, main_frame.WxLogHandler) for h in logger.handlers) == 0
    )

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
    from app import i18n
    from app.main import APP_NAME, LOCALE_DIR

    i18n.install(APP_NAME, LOCALE_DIR, ["en"])

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


def test_main_frame_select_any_column_updates_editor(monkeypatch, tmp_path):
    from app.core.store import save

    save(tmp_path, _sample_requirement())

    wx, app, frame = _prepare_frame(monkeypatch, tmp_path)

    # Add an extra column so clicks on it should still update the editor
    frame.panel.set_columns(["id"])
    frame.panel.set_requirements(frame.model.get_all())

    class DummyEvent:
        def GetData(self):
            return 0

        def GetIndex(self):
            return 0

    frame.editor.Hide()
    frame.editor.fields["title"].SetValue("")

    frame.on_requirement_selected(DummyEvent())

    assert frame.editor.fields["title"].GetValue() == "Title"

    frame.Destroy()
    app.Destroy()
