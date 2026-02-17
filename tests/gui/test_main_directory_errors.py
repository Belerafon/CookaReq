"""Tests for error handling when loading requirement directories."""

from __future__ import annotations

import json

import pytest

from app.config import ConfigManager
from app.settings import MCPSettings


pytestmark = pytest.mark.gui


def _build_frame(tmp_path, gui_context):
    import app.ui.main_frame as main_frame

    config = ConfigManager(path=tmp_path / "config.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))
    frame = main_frame.MainFrame(None, context=gui_context, config=config)
    return frame, main_frame


def test_load_directory_reports_validation_error(tmp_path, wx_app, gui_context, intercept_message_box):
    wx = pytest.importorskip("wx")

    root_dir = tmp_path / "requirements"
    invalid_dir = root_dir / "SYS1"
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "document.json").write_text(
        json.dumps({"prefix": "SYS"}),
        encoding="utf-8",
    )

    frame, main_frame = _build_frame(tmp_path, gui_context)
    frame._load_directory(root_dir)

    assert intercept_message_box, "error message should be shown for invalid document structure"
    message, caption, style = intercept_message_box[-1]
    assert "Failed to load requirements folder" in message
    assert "document prefix mismatch" in message
    assert root_dir.name in message
    assert str(root_dir) not in message
    assert invalid_dir.name in message
    assert caption == main_frame._("Error")
    assert style == wx.ICON_ERROR
    assert frame.docs_controller is None
    assert frame.current_dir is None
    assert str(root_dir) not in frame.recent_dirs

    frame.Destroy()


def test_load_directory_reports_wrong_level_hint_for_document_folder(
    tmp_path, wx_app, gui_context, intercept_message_box
):
    wx = pytest.importorskip("wx")

    document_dir = tmp_path / "SYS"
    document_dir.mkdir(parents=True)
    (document_dir / "document.json").write_text(
        json.dumps({"title": "System"}),
        encoding="utf-8",
    )
    (document_dir / "items").mkdir()

    frame, main_frame = _build_frame(tmp_path, gui_context)
    frame._load_directory(document_dir)

    assert intercept_message_box
    message, caption, style = intercept_message_box[-1]
    assert "single document" in message.lower()
    assert document_dir.parent.name in message
    assert str(document_dir.parent) not in message
    assert caption == main_frame._("Error")
    assert style == wx.ICON_ERROR
    assert frame.docs_controller is None
    assert frame.current_dir is None

    frame.Destroy()


def test_load_directory_warns_about_new_directory_without_documents(
    tmp_path, wx_app, gui_context, intercept_message_box
):
    wx = pytest.importorskip("wx")

    frame, main_frame = _build_frame(tmp_path, gui_context)
    frame._load_directory(tmp_path)

    assert intercept_message_box
    message, caption, style = intercept_message_box[-1]
    assert "No requirement documents were found" in message
    assert "new directory" in message
    assert str(tmp_path) in message
    assert caption == main_frame._("Information")
    assert style == wx.ICON_INFORMATION

    assert frame.docs_controller is not None
    assert frame.current_dir == tmp_path

    frame.Destroy()


def test_load_directory_reports_hint_for_internal_cookareq_folder(
    tmp_path, wx_app, gui_context, intercept_message_box
):
    wx = pytest.importorskip("wx")

    doc_dir = tmp_path / "SYS"
    doc_dir.mkdir(parents=True)
    (doc_dir / "document.json").write_text(
        json.dumps({"title": "System"}),
        encoding="utf-8",
    )

    internal_dir = tmp_path / ".cookareq"
    internal_dir.mkdir()

    frame, main_frame = _build_frame(tmp_path, gui_context)
    frame._load_directory(internal_dir)

    assert intercept_message_box
    message, caption, style = intercept_message_box[-1]
    assert "internal CookaReq data" in message
    assert "parent folder" in message
    assert str(internal_dir) not in message
    assert caption == main_frame._("Error")
    assert style == wx.ICON_ERROR
    assert frame.docs_controller is None
    assert frame.current_dir is None

    frame.Destroy()


@pytest.mark.parametrize("nested_name", ["items", "assets"])
def test_load_directory_reports_hint_for_document_subfolders(
    tmp_path, wx_app, gui_context, intercept_message_box, nested_name
):
    wx = pytest.importorskip("wx")

    doc_dir = tmp_path / "SYS"
    doc_dir.mkdir(parents=True)
    (doc_dir / "document.json").write_text(
        json.dumps({"title": "System"}),
        encoding="utf-8",
    )
    (doc_dir / "items").mkdir()
    nested_dir = doc_dir / nested_name
    nested_dir.mkdir(exist_ok=True)

    frame, main_frame = _build_frame(tmp_path, gui_context)
    frame._load_directory(nested_dir)

    assert intercept_message_box
    message, caption, style = intercept_message_box[-1]
    assert f'"{nested_name}" subfolder' in message
    assert "open requirements root" in message.lower()
    assert str(nested_dir) not in message
    assert caption == main_frame._("Error")
    assert style == wx.ICON_ERROR
    assert frame.docs_controller is None
    assert frame.current_dir is None

    frame.Destroy()
