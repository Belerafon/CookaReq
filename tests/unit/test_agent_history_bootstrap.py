from __future__ import annotations

import zipfile
from pathlib import Path

from app.ui.agent_chat_panel.bootstrap import prepare_history_for_directory
from app.ui.agent_chat_panel.paths import history_path_for_documents


def _write_zip(target: Path, inner_name: str, payload: bytes) -> None:
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr(inner_name, payload)


def test_prepare_history_extracts_archive(tmp_path):
    archive_path = tmp_path / "agent_chats.zip"
    payload = b"demo-archive"
    _write_zip(archive_path, "agent_chats.sqlite", payload)

    result = prepare_history_for_directory(tmp_path)

    history_path = history_path_for_documents(tmp_path)
    assert result.path == history_path
    assert result.seed_source == archive_path
    assert result.seed_kind == "archive"
    assert history_path.read_bytes() == payload


def test_prepare_history_uses_existing_sqlite(tmp_path):
    seed_path = tmp_path / "agent_chats.sqlite"
    payload = b"seed-file"
    seed_path.write_bytes(payload)

    result = prepare_history_for_directory(tmp_path)

    history_path = history_path_for_documents(tmp_path)
    assert result.path == history_path
    assert result.seed_source == seed_path
    assert result.seed_kind == "file"
    assert history_path.read_bytes() == payload


def test_prepare_history_no_seed_creates_parent(tmp_path):
    result = prepare_history_for_directory(tmp_path)

    history_path = history_path_for_documents(tmp_path)
    assert result.path == history_path
    assert not history_path.exists()
