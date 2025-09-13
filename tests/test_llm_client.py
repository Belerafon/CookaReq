import json
import logging
from pathlib import Path

import wx

from app.log import logger
from app.llm.client import LLMClient
from app.mcp.server import JsonlHandler
from tests.llm_utils import cfg_from_env


def test_check_llm(tmp_path: Path) -> None:
    cfg = cfg_from_env("CookaReq-LLM-Test")
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
