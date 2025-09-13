import json
import logging
from pathlib import Path

from app.log import logger
from app.agent import LocalAgent
from app.mcp.server import JsonlHandler, start_server, stop_server
from tests.llm_utils import cfg_with_mcp
from tests.mcp_utils import _wait_until_ready


def test_run_command_list_logs(tmp_path: Path) -> None:
    port = 8140
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        cfg = cfg_with_mcp("127.0.0.1", port, str(tmp_path), "", app_name="CookaReq-Cmd-Test")
        client = LocalAgent(cfg)
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


def test_run_command_error_logs(tmp_path: Path) -> None:
    port = 8141
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        cfg = cfg_with_mcp("127.0.0.1", port, str(tmp_path), "", app_name="CookaReq-Cmd-Test")
        client = LocalAgent(cfg)
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

