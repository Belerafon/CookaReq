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


def test_editor_panel_discard_changes_without_storage_restores_form_state(wx_app):
    pytest.importorskip("wx")
    import wx

    from app.ui.editor_panel import EditorPanel

    frame = wx.Frame(None)
    try:
        panel = EditorPanel(frame)
        panel.fields["title"].ChangeValue("Original")
        panel.notes_ctrl.ChangeValue("Base note")
        panel.attachments = [{"path": "doc.txt", "note": "ref"}]
        panel.mark_clean()

        panel.fields["title"].ChangeValue("Changed")
        panel.notes_ctrl.ChangeValue("New note")
        panel.attachments.clear()
        assert panel.is_dirty() is True

        panel.discard_changes()

        assert panel.fields["title"].GetValue() == "Original"
        assert panel.notes_ctrl.GetValue() == "Base note"
        assert panel.attachments == [{"path": "doc.txt", "note": "ref"}]
        assert panel.is_dirty() is False
    finally:
        frame.Destroy()


def test_editor_panel_discard_changes_uses_callback(wx_app):
    pytest.importorskip("wx")
    import wx

    from app.ui.editor_panel import EditorPanel

    frame = wx.Frame(None)
    try:
        handled: list[str] = []

        def on_discard() -> bool:
            handled.append(panel.fields["title"].GetValue())
            panel.fields["title"].ChangeValue("Callback title")
            panel.notes_ctrl.ChangeValue("Callback note")
            panel.mark_clean()
            return True

        panel = EditorPanel(frame, on_discard=on_discard)
        panel.fields["title"].ChangeValue("Original")
        panel.notes_ctrl.ChangeValue("Note")
        panel.mark_clean()

        panel.fields["title"].ChangeValue("Dirty")
        panel.notes_ctrl.ChangeValue("Dirty note")
        assert panel.is_dirty() is True

        panel.discard_changes()

        assert handled == ["Dirty"]
        assert panel.fields["title"].GetValue() == "Callback title"
        assert panel.notes_ctrl.GetValue() == "Callback note"
        assert panel.is_dirty() is False
    finally:
        frame.Destroy()
