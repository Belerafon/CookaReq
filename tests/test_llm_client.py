import json
import logging
import os
from pathlib import Path

import wx

from app.log import logger
from app.llm.client import LLMClient
from app.mcp.server import JsonlHandler


def _cfg_from_env() -> wx.Config:
    api_key = os.environ.get("OPEN_ROUTER", "")
    app = wx.App()
    cfg = wx.Config(appName="CookaReq-LLM-Test", style=wx.CONFIG_USE_LOCAL_FILE)
    cfg.Write("llm_api_base", "https://openrouter.ai/api/v1")
    cfg.Write("llm_model", "openai/gpt-oss-20b:free")
    cfg.Write("llm_api_key", api_key)
    cfg.Flush()
    app.Destroy()
    return cfg


def test_check_llm(tmp_path: Path) -> None:
    cfg = _cfg_from_env()
    client = LLMClient(cfg)
    log_file = tmp_path / "llm.jsonl"
    handler = JsonlHandler(str(log_file))
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        result = client.check_llm()
    finally:
        logger.setLevel(prev_level)
        logger.removeHandler(handler)
    assert result == {"ok": True}
    entries = [json.loads(line) for line in log_file.read_text().splitlines()]
    req = next(e for e in entries if e.get("event") == "LLM_REQUEST")
    res = next(e for e in entries if e.get("event") == "LLM_RESPONSE")
    assert req["api_key"] == "[REDACTED]"
    assert res["ok"] is True
