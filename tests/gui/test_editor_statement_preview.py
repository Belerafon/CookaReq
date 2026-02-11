"""Tests for statement preview in the editor panel."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.document_store import Document
from app.services.requirements import RequirementsService

pytestmark = pytest.mark.gui


@pytest.mark.gui_smoke
def test_statement_preview_toggle_renders_markdown(wx_app, tmp_path: Path) -> None:
    pytest.importorskip("wx")
    import wx

    from app.ui.editor_panel import EditorPanel

    frame = wx.Frame(None)
    try:
        editor = EditorPanel(frame)
        service = RequirementsService(tmp_path)
        service.save_document(Document(prefix="SYS", title="System"))
        editor.set_service(service)
        editor.set_document("SYS")
        editor.fields["statement"].ChangeValue("Hello **World**")

        editor._set_statement_preview_mode(True)

        preview = editor._statement_preview
        assert preview is not None
        assert preview.IsShown()
        assert preview.GetBackgroundColour() == wx.WHITE
        plain = preview.GetPlainText()
        assert "Hello" in plain
        assert "World" in plain
    finally:
        frame.Destroy()


@pytest.mark.gui_smoke
def test_statement_preview_rewrites_attachment_links(wx_app, tmp_path: Path) -> None:
    pytest.importorskip("wx")
    import wx

    from app.ui.editor_panel import EditorPanel

    frame = wx.Frame(None)
    try:
        editor = EditorPanel(frame)
        service = RequirementsService(tmp_path)
        service.save_document(Document(prefix="SYS", title="System"))
        editor.set_service(service)
        editor.set_document("SYS")

        asset_dir = tmp_path / "SYS" / "assets"
        asset_dir.mkdir(parents=True)
        image_path = asset_dir / "diagram.png"
        image_path.write_text("x", encoding="utf-8")

        editor.attachments = [
            {"id": "att-1", "path": "assets/diagram.png", "note": ""},
        ]
        editor.fields["statement"].ChangeValue("![Diagram](attachment:att-1)")

        rendered = editor._statement_markdown_for_preview()
        assert image_path.resolve().as_uri() in rendered
    finally:
        frame.Destroy()
