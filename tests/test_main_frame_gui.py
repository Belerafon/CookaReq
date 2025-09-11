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

    from app.ui.main_frame import MainFrame
    from app.ui.list_panel import ListPanel

    frame = MainFrame(None)

    # emulate menu event
    evt = wx.CommandEvent(wx.EVT_MENU.typeId, wx.ID_OPEN)
    frame.ProcessEvent(evt)

    assert called == {"init": True, "show": True, "destroy": True}
    assert isinstance(frame.panel, ListPanel)

    frame.Destroy()
    app.Destroy()
