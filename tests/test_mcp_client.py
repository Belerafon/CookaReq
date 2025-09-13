import json
import logging
from pathlib import Path

import wx

from app.log import logger
from app.mcp.client import MCPClient
from app.mcp.server import JsonlHandler, start_server, stop_server
from tests.mcp_utils import _wait_until_ready


def _cfg_with_settings(host: str, port: int, base_path: str, token: str) -> wx.Config:
    app = wx.App()
    cfg = wx.Config(appName="CookaReq-Test", style=wx.CONFIG_USE_LOCAL_FILE)
    cfg.Write("mcp_host", host)
    cfg.WriteInt("mcp_port", port)
    cfg.Write("mcp_base_path", base_path)
    cfg.Write("mcp_token", token)
    cfg.Flush()
    app.Destroy()
    return cfg


def test_check_tools_success(tmp_path: Path) -> None:
    port = 8134
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        cfg = _cfg_with_settings("127.0.0.1", port, str(tmp_path), "")
        client = MCPClient(cfg)
        log_file = tmp_path / "log.jsonl"
        handler = JsonlHandler(str(log_file))
        logger.addHandler(handler)
        prev_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            result = client.check_tools()
        finally:
            logger.setLevel(prev_level)
            logger.removeHandler(handler)
        assert result == {"ok": True}
        lines = log_file.read_text().splitlines()
        entries = [json.loads(line) for line in lines]
        call = next(e for e in entries if e.get("event") == "TOOL_CALL")
        res = next(e for e in entries if e.get("event") == "TOOL_RESULT")
        assert call["payload"]["params"]["token"] == "[REDACTED]"
        assert res["payload"]["ok"] is True
        assert "duration_ms" in res
    finally:
        stop_server()


def test_check_tools_unauthorized(tmp_path: Path) -> None:
    port = 8135
    stop_server()
    start_server(port=port, base_path=str(tmp_path), token="secret")
    try:
        _wait_until_ready(port)
        cfg = _cfg_with_settings("127.0.0.1", port, str(tmp_path), "wrong")
        client = MCPClient(cfg)
        result = client.check_tools()
        assert result["code"] == "UNAUTHORIZED"
    finally:
        stop_server()
