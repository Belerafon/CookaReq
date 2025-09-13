import json
import logging
import os
from pathlib import Path

from app.log import logger
from app.agent import LocalAgent
from app.mcp.server import JsonlHandler, start_server, stop_server
from tests.llm_utils import make_openai_mock, settings_with_mcp
from tests.mcp_utils import _wait_until_ready


def test_run_command_list_logs(tmp_path: Path, monkeypatch) -> None:
    port = 8140
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        settings = settings_with_mcp(
            "127.0.0.1", port, str(tmp_path), "", tmp_path=tmp_path
        )
        if not os.environ.get("OPENROUTER_REAL"):
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
    finally:
        stop_server()


def test_run_command_error_logs(tmp_path: Path, monkeypatch) -> None:
    port = 8141
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        settings = settings_with_mcp(
            "127.0.0.1", port, str(tmp_path), "", tmp_path=tmp_path
        )
        if not os.environ.get("OPENROUTER_REAL"):
            # Установите OPENROUTER_REAL=1 для интеграционного теста с API.
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
    finally:
        stop_server()

