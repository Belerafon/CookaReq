"""Tests for error handling when loading requirement directories."""

from __future__ import annotations

import json

import pytest

from app.config import ConfigManager
from app.settings import MCPSettings


pytestmark = pytest.mark.gui


def test_load_directory_reports_validation_error(tmp_path, monkeypatch, wx_app):
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

    frame = main_frame.MainFrame(None, config=config)

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
