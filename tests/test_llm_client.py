"""Tests for llm client."""

import json
import logging
from pathlib import Path

import pytest

from app.log import logger
from app.llm.client import LLMClient
from app.mcp.server import JsonlHandler
from tests.llm_utils import make_openai_mock, settings_with_llm
from app.settings import LLMSettings


def test_missing_api_key_ignores_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")
    settings = LLMSettings(api_base="https://example", model="foo", api_key="")
    with pytest.raises(ValueError):
        LLMClient(settings)


def test_check_llm(tmp_path: Path, monkeypatch) -> None:
    settings = settings_with_llm(tmp_path)
    monkeypatch.setattr(
        "openai.OpenAI", make_openai_mock({"ping": ("noop", {})})
    )
    client = LLMClient(settings.llm)
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
    assert req["payload"]["api_key"] == "[REDACTED]"
    assert res["payload"]["ok"] is True
    assert "timestamp" in req and "size_bytes" in req
    assert "duration_ms" in res
