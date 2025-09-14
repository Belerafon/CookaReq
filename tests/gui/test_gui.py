"""Tests for gui."""

import pytest


def test_gui_imports(wx_app):
    wx = pytest.importorskip("wx")
    from app.main import main
    from app.ui.main_frame import MainFrame
    from app.ui.list_panel import ListPanel
    from app.ui.editor_panel import EditorPanel

    frame = MainFrame(None)
    list_panel = ListPanel(frame)
    editor_panel = EditorPanel(frame)
    assert list_panel.GetParent() is frame
    assert editor_panel.GetParent() is frame
    assert callable(main)
