"""Tests for tool logging."""

import json
import logging
from pathlib import Path

import pytest

from app.core.document_store import Document, save_document
from app.log import logger
from app.mcp.server import JsonlHandler
from app.mcp.tools_read import list_requirements
from app.mcp.utils import log_tool

pytestmark = pytest.mark.integration


def test_tool_logging(tmp_path: Path) -> None:
    log_file = tmp_path / "server.jsonl"
    handler = JsonlHandler(str(log_file))
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    doc = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", doc)
    try:
        result = list_requirements(tmp_path, prefix="SYS")
    finally:
        logger.setLevel(prev_level)
        logger.removeHandler(handler)
    data = json.loads(log_file.read_text().splitlines()[0])
    assert data["tool"] == "list_requirements"
    assert data["params"]["directory"] == str(tmp_path)
    assert "result" in data
    assert data["result"] == result
    assert "timestamp" in data


def test_log_tool_sanitizes_and_truncates(tmp_path: Path) -> None:
    log_file = tmp_path / "server.jsonl"
    handler = JsonlHandler(str(log_file))
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        log_tool("dummy", {"token": "secret"}, "x" * 20, max_result_length=10)
    finally:
        logger.setLevel(prev_level)
        logger.removeHandler(handler)
    data = json.loads(log_file.read_text().splitlines()[0])
    assert data["params"]["token"] == "[REDACTED]"
    assert data["result"] == "xxxxxxxxxx..."
