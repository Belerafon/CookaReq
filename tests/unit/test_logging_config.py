"""Tests for logging config."""

import logging
from pathlib import Path

import pytest

import app.log as log_module
from app.log import (
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
    prev_state = (
        log_module._log_dir,
        log_module._text_log_path,
        log_module._json_log_path,
    )
    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)
    log_module._log_dir = None
    log_module._text_log_path = None
    log_module._json_log_path = None
    try:
        yield
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers.clear()
        logger.handlers.extend(prev_handlers)
        logger.setLevel(prev_level)
        (
            log_module._log_dir,
            log_module._text_log_path,
            log_module._json_log_path,
        ) = prev_state


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
    file_handlers = [h for h in handlers if isinstance(h, logging.FileHandler)]
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
    configure_logging(level=logging.WARNING)
    assert logger.level == logging.DEBUG
    assert stream_handler.level == logging.DEBUG


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


def test_configure_logging_rotates_previous_run(
    reset_logger: None, log_dir_env: Path
) -> None:
    text_path = log_dir_env / log_module._TEXT_LOG_NAME
    json_path = log_dir_env / log_module._JSON_LOG_NAME
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text("old text log", encoding="utf-8")
    json_path.write_text("{\"message\": \"old json\"}\n", encoding="utf-8")

    configure_logging()

    rotated_text = log_dir_env / f"{log_module._TEXT_LOG_NAME}.1"
    rotated_json = log_dir_env / f"{log_module._JSON_LOG_NAME}.1"
    assert rotated_text.exists()
    assert rotated_json.exists()
    assert rotated_text.read_text(encoding="utf-8") == "old text log"
    assert rotated_json.read_text(encoding="utf-8") == "{\"message\": \"old json\"}\n"
    assert text_path.exists()
    assert json_path.exists()
