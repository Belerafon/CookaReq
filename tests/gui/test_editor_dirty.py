"""Tests for editor dirty state tracking."""

import pytest


pytestmark = pytest.mark.gui


def test_editor_panel_dirty_detection_fields(wx_app):
    pytest.importorskip("wx")
    import wx

    from app.ui.editor_panel import EditorPanel

    frame = wx.Frame(None)
    try:
        panel = EditorPanel(frame)
        panel.mark_clean()
        assert panel.is_dirty() is False

        panel.fields["title"].ChangeValue("Sample")
        assert panel.is_dirty() is True

        panel.fields["title"].ChangeValue("")
        assert panel.is_dirty() is False
    finally:
        frame.Destroy()


def test_editor_panel_mark_clean_resets_dirty(wx_app):
    pytest.importorskip("wx")
    import wx

    from app.ui.editor_panel import EditorPanel

    frame = wx.Frame(None)
    try:
        panel = EditorPanel(frame)
        panel.fields["title"].ChangeValue("Initial")
        assert panel.is_dirty() is True

        panel.mark_clean()
        assert panel.is_dirty() is False

        panel.fields["title"].ChangeValue("Updated")
        assert panel.is_dirty() is True
    finally:
        frame.Destroy()
