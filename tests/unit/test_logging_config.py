"""Tests for logging config."""

import logging
from pathlib import Path

import pytest

import app.log as log_module
from app.log import (
    ConsoleFormatter,
    JsonlHandler,
    configure_logging,
    get_log_directory,
    get_log_file_paths,
    logger,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def reset_logger() -> None:
    prev_handlers = list(logger.handlers)
    prev_level = logger.level
    prev_log_dir = log_module._log_dir
    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)
    log_module._log_dir = None
    try:
        yield
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()
        logger.handlers.extend(prev_handlers)
        logger.setLevel(prev_level)
        log_module._log_dir = prev_log_dir


@pytest.fixture
def log_dir_env(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "logs"
    monkeypatch.setenv("COOKAREQ_LOG_DIR", str(path))
    return path


def test_configure_logging_attaches_handlers_once(
    reset_logger: None, log_dir_env: Path
) -> None:
    configure_logging()
    handlers = list(logger.handlers)
    assert len(handlers) == 3
    stream_handlers = [
        h
        for h in handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
    ]
    file_handlers = [
        h
        for h in handlers
        if isinstance(h, logging.FileHandler) and not isinstance(h, JsonlHandler)
    ]
    json_handlers = [h for h in handlers if isinstance(h, JsonlHandler)]
    assert len(stream_handlers) == 1
    assert len(file_handlers) == 1
    assert len(json_handlers) == 1
    configure_logging()
    assert logger.handlers == handlers


def test_configure_logging_sets_console_level(
    reset_logger: None, log_dir_env: Path
) -> None:
    configure_logging(level=logging.DEBUG)
    assert logger.level == logging.DEBUG
    stream_handler = next(
        h
        for h in logger.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
    )
    assert stream_handler.level == logging.DEBUG
    assert isinstance(stream_handler.formatter, ConsoleFormatter)
    configure_logging(level=logging.WARNING)
    assert logger.level == logging.DEBUG
    assert stream_handler.level == logging.DEBUG


def test_console_formatter_appends_payload_when_message_is_event(
    reset_logger: None, log_dir_env: Path
) -> None:
    configure_logging(level=logging.DEBUG)
    stream_handler = next(
        h
        for h in logger.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
    )
    formatter = stream_handler.formatter
    assert isinstance(formatter, ConsoleFormatter)

    record = logging.LogRecord(
        name="cookareq",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="LLM_REQUEST",
        args=(),
        exc_info=None,
    )
    record.json = {
        "event": "LLM_REQUEST",
        "payload": {"rid": "HLR1"},
        "size_bytes": 10,
    }
    assert formatter.format(record).endswith('{"rid": "HLR1"}')


def test_console_formatter_skips_when_message_contains_payload(
    reset_logger: None, log_dir_env: Path
) -> None:
    configure_logging(level=logging.DEBUG)
    stream_handler = next(
        h
        for h in logger.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
    )
    formatter = stream_handler.formatter
    assert isinstance(formatter, ConsoleFormatter)

    payload = {"event": "LLM_REQUEST", "payload": {"rid": "HLR1"}}
    record = logging.LogRecord(
        name="cookareq",
        level=logging.DEBUG,
        pathname=__file__,
        lineno=0,
        msg="LLM_REQUEST {" + '"rid": "HLR1"' + "}",
        args=(),
        exc_info=None,
    )
    record.json = payload
    formatted = formatter.format(record)
    assert formatted.count('"rid": "HLR1"') == 1
def test_log_directory_and_files_created(
    reset_logger: None, log_dir_env: Path
) -> None:
    configure_logging()
    directory = get_log_directory()
    assert directory == log_dir_env
    assert directory.exists()
    text_path, json_path = get_log_file_paths()
    assert text_path.parent == directory
    assert json_path.parent == directory
    assert text_path.name.endswith(".log")
    assert json_path.name.endswith(".jsonl")


def test_configure_logging_preserves_small_logs(
    reset_logger: None, log_dir_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(log_module, "_TEXT_LOG_MAX_BYTES", 64)
    monkeypatch.setattr(log_module, "_JSON_LOG_MAX_BYTES", 64)
    text_path = log_dir_env / log_module._TEXT_LOG_NAME
    json_path = log_dir_env / log_module._JSON_LOG_NAME
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text("old text log", encoding="utf-8")
    json_path.write_text("{\"message\": \"old json\"}\n", encoding="utf-8")

    configure_logging()

    assert not (log_dir_env / f"{log_module._TEXT_LOG_NAME}.1").exists()
    assert not (log_dir_env / f"{log_module._JSON_LOG_NAME}.1").exists()
    assert text_path.read_text(encoding="utf-8") == "old text log"
    assert (
        json_path.read_text(encoding="utf-8")
        == "{\"message\": \"old json\"}\n"
    )


def test_configure_logging_rotates_full_logs(
    reset_logger: None, log_dir_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(log_module, "_TEXT_LOG_MAX_BYTES", 32)
    monkeypatch.setattr(log_module, "_JSON_LOG_MAX_BYTES", 40)
    text_path = log_dir_env / log_module._TEXT_LOG_NAME
    json_path = log_dir_env / log_module._JSON_LOG_NAME
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_payload = "x" * 32
    json_payload = "{" + "x" * 42 + "}\n"
    text_path.write_text(text_payload, encoding="utf-8")
    json_path.write_text(json_payload, encoding="utf-8")

    configure_logging()

    rotated_text = log_dir_env / f"{log_module._TEXT_LOG_NAME}.1"
    rotated_json = log_dir_env / f"{log_module._JSON_LOG_NAME}.1"
    assert rotated_text.exists()
    assert rotated_json.exists()
    assert rotated_text.read_text(encoding="utf-8") == text_payload
    assert rotated_json.read_text(encoding="utf-8") == json_payload
    assert text_path.stat().st_size == 0
    assert json_path.stat().st_size == 0


def test_jsonl_handler_rotates_when_size_exceeded(tmp_path: Path) -> None:
    log_path = tmp_path / "data.jsonl"
    handler = JsonlHandler(
        log_path,
        max_bytes=60,
        backup_count=2,
    )
    try:
        record = logging.LogRecord(
            name="cookareq.test",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg="message %s",
            args=("one",),
            exc_info=None,
        )
        for _ in range(5):
            handler.handle(record)
        assert log_path.exists()
        rotated = sorted(tmp_path.glob("data.jsonl.*"))
        assert rotated, "rotation did not create backup files"
        assert any(r.suffix == ".1" for r in rotated)
    finally:
        handler.close()
