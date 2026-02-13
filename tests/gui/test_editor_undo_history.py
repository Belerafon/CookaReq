"""Tests for custom text undo/redo history in editor panel."""

import pytest


pytestmark = pytest.mark.gui


@pytest.mark.gui_smoke
def test_editor_text_history_undo_redo(wx_app):
    pytest.importorskip("wx")
    import wx

    from app.ui.editor_panel import EditorPanel

    frame = wx.Frame(None)
    try:
        panel = EditorPanel(frame)
        ctrl = panel.fields["statement"]

        for value in ("a", "ab", "abc"):
            ctrl.ChangeValue(value)
            panel._on_text_history_change(ctrl, wx.CommandEvent(wx.wxEVT_TEXT))

        assert ctrl.GetValue() == "abc"
        assert panel._undo_text_history(ctrl) is True
        assert ctrl.GetValue() == "ab"
        assert panel._undo_text_history(ctrl) is True
        assert ctrl.GetValue() == "a"
        assert panel._redo_text_history(ctrl) is True
        assert ctrl.GetValue() == "ab"
    finally:
        frame.Destroy()


@pytest.mark.gui_smoke
def test_editor_text_history_keeps_ten_steps(wx_app):
    pytest.importorskip("wx")
    import wx

    from app.ui.editor_panel import EditorPanel

    frame = wx.Frame(None)
    try:
        panel = EditorPanel(frame)
        ctrl = panel.fields["title"]

        for idx in range(1, 13):
            ctrl.ChangeValue(f"value-{idx}")
            panel._on_text_history_change(ctrl, wx.CommandEvent(wx.wxEVT_TEXT))

        undone = 0
        while panel._undo_text_history(ctrl):
            undone += 1

        assert undone == 10
        assert ctrl.GetValue() == "value-2"
    finally:
        frame.Destroy()
