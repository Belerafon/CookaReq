"""GUI smoke tests for inserting images into statements."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.document_store import Document
from app.services.requirements import RequirementsService

pytestmark = pytest.mark.gui


@pytest.mark.gui_smoke
def test_insert_attachment_markdown_updates_statement(wx_app, tmp_path: Path) -> None:
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

        image_path = tmp_path / "image.png"
        image_path.write_text("data", encoding="utf-8")
        attachment = service.upload_requirement_attachment("SYS", image_path)
        editor.attachments.append(attachment)
        editor._refresh_attachments()

        editor.fields["statement"].ChangeValue("")
        editor._insert_attachment_markdown(attachment["id"], "Diagram")

        statement = editor.fields["statement"].GetValue()
        assert f"attachment:{attachment['id']}" in statement
        assert "Diagram" in statement
    finally:
        frame.Destroy()


@pytest.mark.gui_smoke
def test_insert_statement_snippet_appends_text(wx_app) -> None:
    pytest.importorskip("wx")
    import wx

    from app.ui.editor_panel import EditorPanel

    frame = wx.Frame(None)
    try:
        editor = EditorPanel(frame)
        editor.fields["statement"].ChangeValue("Start ")
        editor.fields["statement"].SetInsertionPointEnd()
        editor._insert_statement_snippet("**Bold**")

        statement = editor.fields["statement"].GetValue()
        assert statement.endswith("**Bold**")
    finally:
        frame.Destroy()
