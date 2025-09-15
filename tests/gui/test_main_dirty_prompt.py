"""Tests for MainFrame dirty-state confirmation logic."""

import pytest


pytestmark = pytest.mark.gui


def test_confirm_discard_changes(monkeypatch, wx_app):
    pytest.importorskip("wx")

    import app.ui.main_frame as main_frame_mod

    frame = main_frame_mod.MainFrame(None)
    try:
        frame.editor.fields["title"].ChangeValue("Dirty")
        assert frame.editor.is_dirty() is True

        messages: list[str] = []

        def reject(message: str) -> bool:
            messages.append(message)
            return False

        monkeypatch.setattr(main_frame_mod, "confirm", reject)

        assert frame._confirm_discard_changes() is False
        assert messages[-1] == main_frame_mod._("Discard unsaved changes?")
        assert frame.editor.is_dirty() is True

        def accept(message: str) -> bool:
            messages.append(message)
            return True

        monkeypatch.setattr(main_frame_mod, "confirm", accept)

        assert frame._confirm_discard_changes() is True
        assert messages[-1] == main_frame_mod._("Discard unsaved changes?")
        assert frame.editor.is_dirty() is False
    finally:
        frame.Destroy()
