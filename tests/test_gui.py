import pytest


def test_gui_imports():
    wx = pytest.importorskip("wx")
    from app.main import main
    from app.ui.main_frame import MainFrame
    from app.ui.list_panel import ListPanel

    app = wx.App()
    frame = MainFrame(None)
    panel = ListPanel(frame)
    assert panel.GetParent() is frame
    assert callable(main)
