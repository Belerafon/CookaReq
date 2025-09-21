"""Tests for MCP request logging rotation behaviour."""

import logging
from pathlib import Path

import pytest

import app.log as log_module
import app.mcp.server as server_module

pytestmark = pytest.mark.unit


@pytest.fixture
def reset_request_logging() -> None:
    prev_handlers = list(log_module.logger.handlers)
    prev_level = log_module.logger.level
    prev_log_dir = log_module._log_dir

    prev_request_handlers = list(server_module.request_logger.handlers)
    prev_request_level = server_module.request_logger.level
    prev_request_propagate = server_module.request_logger.propagate

    log_module.logger.handlers.clear()
    log_module.logger.setLevel(logging.NOTSET)
    log_module._log_dir = None

    server_module.request_logger.handlers.clear()
    server_module.request_logger.setLevel(logging.INFO)
    server_module.request_logger.propagate = False
    try:
        yield
    finally:
        for handler in server_module.request_logger.handlers:
            handler.close()
        server_module.request_logger.handlers.clear()
        server_module.request_logger.handlers.extend(prev_request_handlers)
        server_module.request_logger.setLevel(prev_request_level)
        server_module.request_logger.propagate = prev_request_propagate

        for handler in log_module.logger.handlers:
            handler.close()
        log_module.logger.handlers.clear()
        log_module.logger.handlers.extend(prev_handlers)
        log_module.logger.setLevel(prev_level)
        log_module._log_dir = prev_log_dir


def _prepare_log_dir(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)


def test_request_logging_preserves_small_files(
    reset_request_logging: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COOKAREQ_LOG_DIR", str(tmp_path / "app"))
    monkeypatch.setattr(server_module, "_REQUEST_LOG_MAX_BYTES", 64)
    monkeypatch.setattr(log_module, "_JSON_LOG_MAX_BYTES", 64)

    _prepare_log_dir(tmp_path)
    text_path = tmp_path / "server.log"
    json_path = tmp_path / "server.jsonl"
    text_path.write_text("existing", encoding="utf-8")
    json_path.write_text("{\"message\": \"old\"}\n", encoding="utf-8")

    resolved = server_module._configure_request_logging(tmp_path)

    assert resolved == tmp_path
    assert not (tmp_path / "server.log.1").exists()
    assert not (tmp_path / "server.jsonl.1").exists()
    assert text_path.read_text(encoding="utf-8") == "existing"
    assert json_path.read_text(encoding="utf-8") == "{\"message\": \"old\"}\n"


def test_request_logging_rotates_full_files(
    reset_request_logging: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COOKAREQ_LOG_DIR", str(tmp_path / "app"))
    monkeypatch.setattr(server_module, "_REQUEST_LOG_MAX_BYTES", 32)
    monkeypatch.setattr(log_module, "_JSON_LOG_MAX_BYTES", 32)

    _prepare_log_dir(tmp_path)
    text_path = tmp_path / "server.log"
    json_path = tmp_path / "server.jsonl"
    text_payload = "x" * 32
    json_payload = "{" + "x" * 30 + "}\n"
    text_path.write_text(text_payload, encoding="utf-8")
    json_path.write_text(json_payload, encoding="utf-8")

    resolved = server_module._configure_request_logging(tmp_path)

    assert resolved == tmp_path
    rotated_text = tmp_path / "server.log.1"
    rotated_json = tmp_path / "server.jsonl.1"
    assert rotated_text.exists()
    assert rotated_json.exists()
    assert rotated_text.read_text(encoding="utf-8") == text_payload
    assert rotated_json.read_text(encoding="utf-8") == json_payload
    assert text_path.stat().st_size == 0
    assert json_path.stat().st_size == 0
