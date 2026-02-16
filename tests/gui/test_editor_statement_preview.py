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

        mode = editor._statement_mode
        assert mode is not None
        assert mode.GetString(1) == "View"

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
def test_statement_preview_renders_single_dollar_formula(wx_app, tmp_path: Path) -> None:
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
        editor.fields["statement"].ChangeValue("Energy: $E = mc^2$")

        editor._set_statement_preview_mode(True)

        preview = editor._statement_preview
        assert preview is not None
        plain = preview.GetPlainText()
        assert "E = mc^2" in plain
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


@pytest.mark.gui_smoke
def test_statement_formula_button_tooltip_and_snippet(wx_app, tmp_path: Path) -> None:
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

        formula_btn = editor._insert_formula_btn
        assert formula_btn is not None
        tooltip = formula_btn.GetToolTipText()
        assert "\\(...\\)" in tooltip
        assert "$$...$$" in tooltip

        editor.fields["statement"].ChangeValue("")
        editor._on_insert_formula(wx.CommandEvent())

        statement = editor.fields["statement"].GetValue()
        assert "\\sqrt{a^2 + b^2}" in statement
        assert "\\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}" in statement
    finally:
        frame.Destroy()
