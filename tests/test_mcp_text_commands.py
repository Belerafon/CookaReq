"""Tests for mcp text commands."""

import json
import logging
from pathlib import Path

from app.log import logger
from app.agent import LocalAgent
from app.mcp.server import JsonlHandler, app as mcp_app
from tests.llm_utils import make_openai_mock, settings_with_mcp


def test_run_command_list_logs(tmp_path: Path, monkeypatch, mcp_server) -> None:
    port = mcp_server
    mcp_app.state.base_path = str(tmp_path)
    settings = settings_with_mcp(
        "127.0.0.1", port, str(tmp_path), "", tmp_path=tmp_path
    )
    # Мокаем OpenAI, чтобы исключить внешние вызовы.
    monkeypatch.setattr(
        "openai.OpenAI",
        make_openai_mock(
            {"list requirements per page 1": ("list_requirements", {"per_page": 1})}
        ),
    )
    client = LocalAgent(settings=settings, confirm=lambda _m: True)
    log_file = tmp_path / "cmd.jsonl"
    handler = JsonlHandler(str(log_file))
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        result = client.run_command("list requirements per page 1")
    finally:
        logger.setLevel(prev_level)
        logger.removeHandler(handler)
    assert result["items"] == []
    entries = [json.loads(line) for line in log_file.read_text().splitlines()]
    events = {e.get("event") for e in entries}
    assert {"LLM_REQUEST", "LLM_RESPONSE", "TOOL_CALL", "TOOL_RESULT", "DONE"} <= events
    


def test_run_command_error_logs(tmp_path: Path, monkeypatch, mcp_server) -> None:
    port = mcp_server
    mcp_app.state.base_path = str(tmp_path)
    settings = settings_with_mcp(
        "127.0.0.1", port, str(tmp_path), "", tmp_path=tmp_path
    )
    # Мокаем OpenAI, чтобы исключить внешние вызовы.
    monkeypatch.setattr(
        "openai.OpenAI",
        make_openai_mock({"get requirement 1": ("get_requirement", {"req_id": 1})}),
    )
    client = LocalAgent(settings=settings, confirm=lambda _m: True)
    log_file = tmp_path / "err.jsonl"
    handler = JsonlHandler(str(log_file))
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        result = client.run_command("get requirement 1")
    finally:
        logger.setLevel(prev_level)
        logger.removeHandler(handler)
    assert "error" in result
    entries = [json.loads(line) for line in log_file.read_text().splitlines()]
    events = {e.get("event") for e in entries}
    assert {"LLM_REQUEST", "LLM_RESPONSE", "TOOL_CALL", "TOOL_RESULT", "ERROR"} <= events
