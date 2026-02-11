"""Tests for error handling when loading requirement directories."""

from __future__ import annotations

import json

import pytest

from app.config import ConfigManager
from app.settings import MCPSettings


pytestmark = pytest.mark.gui


def test_load_directory_reports_validation_error(tmp_path, monkeypatch, wx_app, gui_context):
    wx = pytest.importorskip("wx")
    import app.ui.main_frame as main_frame

    root_dir = tmp_path / "requirements"
    invalid_dir = root_dir / "SYS1"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "document.json").write_text(
        json.dumps({"prefix": "SYS"}),
        encoding="utf-8",
    )

    messages: list[tuple[str, str, int]] = []

    def fake_message(message: str, caption: str, style: int = 0, *args, **kwargs):
        messages.append((message, caption, style))
        return wx.OK

    monkeypatch.setattr(wx, "MessageBox", fake_message)

    config = ConfigManager(path=tmp_path / "config.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))

    frame = main_frame.MainFrame(None, context=gui_context, config=config)

    frame._load_directory(root_dir)

    assert messages, "error message should be shown for invalid document structure"
    message, caption, style = messages[-1]
    assert "Failed to load requirements folder" in message
    assert "document prefix mismatch" in message
    assert str(root_dir) in message
    assert invalid_dir.name in message
    assert caption == main_frame._("Error")
    assert style == wx.ICON_ERROR
    assert frame.docs_controller is None
    assert frame.current_dir is None
    assert str(root_dir) not in frame.recent_dirs

    frame.Destroy()


def test_load_directory_reports_wrong_level_hint_for_document_folder(
    tmp_path, monkeypatch, wx_app, gui_context
):
    wx = pytest.importorskip("wx")
    import app.ui.main_frame as main_frame

    document_dir = tmp_path / "SYS"
    document_dir.mkdir(parents=True)
    (document_dir / "document.json").write_text(
        json.dumps({"title": "System"}),
        encoding="utf-8",
    )
    (document_dir / "items").mkdir()

    messages: list[tuple[str, str, int]] = []

    def fake_message(message: str, caption: str, style: int = 0, *args, **kwargs):
        messages.append((message, caption, style))
        return wx.OK

    monkeypatch.setattr(wx, "MessageBox", fake_message)

    config = ConfigManager(path=tmp_path / "config.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))

    frame = main_frame.MainFrame(None, context=gui_context, config=config)

    frame._load_directory(document_dir)

    assert messages
    message, caption, style = messages[-1]
    assert "single document" in message
    assert str(document_dir.parent) in message
    assert caption == main_frame._("Error")
    assert style == wx.ICON_ERROR
    assert frame.docs_controller is None
    assert frame.current_dir is None

    frame.Destroy()


def test_load_directory_warns_about_new_directory_without_documents(
    tmp_path, monkeypatch, wx_app, gui_context
):
    wx = pytest.importorskip("wx")
    import app.ui.main_frame as main_frame

    messages: list[tuple[str, str, int]] = []

    def fake_message(message: str, caption: str, style: int = 0, *args, **kwargs):
        messages.append((message, caption, style))
        return wx.OK

    monkeypatch.setattr(wx, "MessageBox", fake_message)

    config = ConfigManager(path=tmp_path / "config.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))

    frame = main_frame.MainFrame(None, context=gui_context, config=config)

    frame._load_directory(tmp_path)

    assert messages
    message, caption, style = messages[-1]
    assert "No requirement documents were found" in message
    assert "new directory" in message
    assert str(tmp_path) in message
    assert caption == main_frame._("Information")
    assert style == wx.ICON_INFORMATION

    assert frame.docs_controller is not None
    assert frame.current_dir == tmp_path

    frame.Destroy()
