from __future__ import annotations

import shutil
import sqlite3
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.gui]


def _copy_sample_repository(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[2] / "requirements"
    destination = tmp_path / "requirements"
    shutil.copytree(source, destination)
    return destination


def _create_main_frame(tmp_path: Path, context):
    pytest.importorskip("wx")
    from app.config import ConfigManager
    from app.settings import MCPSettings
    from app.ui.main_frame import MainFrame
    from app.ui.requirement_model import RequirementModel

    config_path = tmp_path / "config.ini"
    config = ConfigManager(path=config_path)
    config.set_mcp_settings(MCPSettings(auto_start=False))
    frame = MainFrame(
        None,
        context=context,
        config=config,
        model=RequirementModel(),
    )
    frame.Show()
    return frame


def test_agent_chat_history_saved_next_to_documents(tmp_path, wx_app, gui_context):
    repository = _copy_sample_repository(tmp_path)
    frame = _create_main_frame(tmp_path, gui_context)
    try:
        wx_app.Yield()
        frame._load_directory(repository)
        wx_app.Yield()

        panel = frame.agent_panel
        expected_history = repository / ".cookareq" / "agent_chats.sqlite"
        expected_settings = repository / ".cookareq" / "agent_settings.json"
        assert panel.history_path == expected_history
        assert panel.project_settings_path == expected_settings

        panel._append_history("ping", "pong", "pong", None, None, None)
        wx_app.Yield()

        assert expected_history.exists()
        with sqlite3.connect(expected_history) as conn:
            conn.row_factory = sqlite3.Row
            conversations = conn.execute("SELECT id FROM conversations").fetchall()
            assert conversations
            conversation_id = conversations[0]["id"]
            row = conn.execute(
                "SELECT payload FROM entries WHERE conversation_id = ? ORDER BY position",
                (conversation_id,),
            ).fetchone()
            assert row is not None
            payload = json.loads(row["payload"])
            assert payload["prompt"] == "ping"
    finally:
        frame.Destroy()
        wx_app.Yield()
