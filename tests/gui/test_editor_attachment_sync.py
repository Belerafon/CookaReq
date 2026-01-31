"""GUI smoke tests for syncing attachments with statement text."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui


@pytest.mark.gui_smoke
def test_sync_attachments_filters_unused_entries(wx_app) -> None:
    pytest.importorskip("wx")
    import wx

    from app.ui.editor_panel import EditorPanel

    frame = wx.Frame(None)
    try:
        editor = EditorPanel(frame)
        editor.attachments = [
            {"id": "keep", "path": "assets/keep.png", "note": ""},
            {"id": "drop", "path": "assets/drop.png", "note": ""},
        ]
        editor.fields["statement"].ChangeValue("![Img](attachment:keep)")

        editor._sync_attachments_with_statement()

        assert editor.attachments == [{"id": "keep", "path": "assets/keep.png", "note": ""}]
    finally:
        frame.Destroy()
