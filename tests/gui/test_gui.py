"""Tests for gui."""

import pytest

pytestmark = pytest.mark.gui


def test_gui_imports(wx_app):
    pytest.importorskip("wx")
    from app.main import main
    from app.ui.editor_panel import EditorPanel
    from app.ui.list_panel import ListPanel
    from app.ui.main_frame import MainFrame

    frame = MainFrame(None)
    list_panel = ListPanel(frame)
    editor_panel = EditorPanel(frame)
    assert list_panel.GetParent() is frame
    assert editor_panel.GetParent() is frame
    assert callable(main)
