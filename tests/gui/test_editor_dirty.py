"""Tests for editor dirty state tracking."""

from contextlib import suppress

import pytest


pytestmark = pytest.mark.gui


@pytest.mark.gui_smoke
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


@pytest.mark.gui_smoke
def test_editor_panel_discard_changes_without_storage_restores_form_state(wx_app):
    pytest.importorskip("wx")
    import wx

    from app.ui.editor_panel import EditorPanel

    frame = wx.Frame(None)
    try:
        panel = EditorPanel(frame)
        panel.fields["title"].ChangeValue("Original")
        panel.notes_ctrl.ChangeValue("Base note")
        panel.attachments = [{"id": "att-1", "path": "doc.txt", "note": "ref"}]
        panel.mark_clean()

        panel.fields["title"].ChangeValue("Changed")
        panel.notes_ctrl.ChangeValue("New note")
        panel.attachments.clear()
        assert panel.is_dirty() is True

        panel.discard_changes()

        assert panel.fields["title"].GetValue() == "Original"
        assert panel.notes_ctrl.GetValue() == "Base note"
        assert panel.attachments == [{"id": "att-1", "path": "doc.txt", "note": "ref"}]
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


def test_editor_panel_buttons_place_cancel_after_save(wx_app):
    pytest.importorskip("wx")
    import wx

    from app.ui.editor_panel import EditorPanel

    frame = wx.Frame(None)
    try:
        panel = EditorPanel(frame)
        sizer = panel.save_btn.GetContainingSizer()
        assert sizer is not None
        windows = [child.GetWindow() for child in sizer.GetChildren() if child.IsWindow()]
        assert windows == [panel.save_btn, panel.cancel_btn]
    finally:
        frame.Destroy()


@pytest.mark.gui_smoke
def test_editor_panel_load_resets_scroll_to_top(wx_app):
    pytest.importorskip("wx")
    import wx

    from app.core.model import Requirement
    from app.ui.editor_panel import EditorPanel

    frame = wx.Frame(None, size=(480, 420))
    try:
        panel = EditorPanel(frame)
        frame.Show()

        first = Requirement.from_mapping(
            {
                "id": 100,
                "statement": "First requirement",
                "notes": "\n".join(f"line {idx}" for idx in range(120)),
                "labels": ["tag-a"],
            }
        )
        panel.load(first)
        wx.Yield()

        panel._content_panel.Scroll(0, 200)
        wx.Yield()
        assert panel._content_panel.GetViewStart()[1] > 0

        second = Requirement.from_mapping(
            {
                "id": 101,
                "statement": "Second requirement",
                "labels": ["tag-b"],
            }
        )
        panel.load(second)
        wx.Yield()

        assert panel._content_panel.GetViewStart()[1] == 0
    finally:
        frame.Destroy()


@pytest.mark.gui_smoke
def test_detached_editor_cancel_closes_window_without_saving(wx_app, tmp_path):
    pytest.importorskip("wx")
    import wx

    from app.core.document_store import LabelDef
    from app.core.model import Requirement
    from app.ui.detached_editor import DetachedEditorFrame

    parent = wx.Frame(None)
    try:
        closed: list[DetachedEditorFrame] = []

        def _on_close(frame: DetachedEditorFrame) -> None:
            closed.append(frame)

        requirement = Requirement.from_mapping({"id": 1, "statement": "Original"})
        frame = DetachedEditorFrame(
            parent,
            requirement=requirement,
            doc_prefix="DOC",
            directory=tmp_path,
            labels=[LabelDef(key="prio", title="Priority")],
            allow_freeform=False,
            on_save=lambda _frame: False,
            on_close=_on_close,
        )
        try:
            frame.editor.fields["title"].ChangeValue("Updated")
            assert frame.editor.is_dirty() is True

            frame.editor.discard_changes()
            wx.Yield()

            assert closed == [frame]
            with pytest.raises(RuntimeError):
                frame.IsShown()
        finally:
            with suppress(RuntimeError):
                frame.Destroy()
    finally:
        parent.Destroy()
