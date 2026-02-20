"""Tests for telemetry."""

import json
import logging
from pathlib import Path

import pytest

import app.telemetry as telemetry
from app.log import JsonlHandler, logger
from app.telemetry import REDACTED, log_debug_payload, log_event, sanitize

pytestmark = pytest.mark.unit


def test_sanitize_redacts_sensitive_keys() -> None:
    data = {
        "token": "secret",
        "Authorization": "Bearer abc",
        "user": "alice",
    }
    sanitized = sanitize(data)
    assert sanitized["token"] == REDACTED
    assert sanitized["Authorization"] == REDACTED
    assert sanitized["user"] == "alice"


def test_sanitize_redacts_nested_sensitive_keys() -> None:
    data = {
        "outer": {
            "Token": "abc",
            "inner": {"password": "p@ss", "value": 42},
        },
        "list": [{"secret": "s"}, {"Authorization": "Bearer"}],
    }
    sanitized = sanitize(data)
    assert sanitized["outer"]["Token"] == REDACTED
    assert sanitized["outer"]["inner"]["password"] == REDACTED
    assert sanitized["outer"]["inner"]["value"] == 42
    assert sanitized["list"][0]["secret"] == REDACTED
    assert sanitized["list"][1]["Authorization"] == REDACTED


def test_log_event_records_size_and_duration_and_sanitizes_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    log_file = tmp_path / "telemetry.jsonl"
    handler = JsonlHandler(str(log_file))
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        monkeypatch.setattr(telemetry.time, "monotonic", lambda: 2.0)
        payload = {
            "token": "secret",
            "foo": "bar",
            "nested": {"password": "p@ss"},
            "list": [{"api_key": "key"}],
        }
        log_event("TEST_EVENT", payload, start_time=1.0)
    finally:
        logger.setLevel(prev_level)
        logger.removeHandler(handler)
    entry = json.loads(log_file.read_text().splitlines()[0])
    sanitized_payload = {
        "token": REDACTED,
        "foo": "bar",
        "nested": {"password": REDACTED},
        "list": [{"api_key": REDACTED}],
    }
    expected_size = len(
        json.dumps(sanitized_payload, ensure_ascii=False).encode("utf-8"),
    )
    assert entry["payload"] == sanitized_payload
    log_text = json.dumps(entry)
    assert "secret" not in log_text
    assert "p@ss" not in log_text
    assert '"key"' not in log_text
    assert entry["size_bytes"] == expected_size
    assert entry["duration_ms"] == 1000


def test_log_debug_payload_emits_full_payload(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    log_file = tmp_path / "debug.jsonl"
    handler = JsonlHandler(str(log_file))
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        with caplog.at_level(logging.DEBUG, logger="cookareq"):
            log_debug_payload(
                "TEST_DEBUG",
                {
                    "token": "secret",
                    "nested": {"password": "hidden"},
                    "list": [{"api_key": "key"}],
                },
            )
    finally:
        logger.setLevel(prev_level)
        logger.removeHandler(handler)
    records = [r for r in caplog.records if r.message == "TEST_DEBUG"]
    assert records, "debug payload log was not emitted"
    message = records[-1].message
    assert message == "TEST_DEBUG"
    # Payload should live in structured extras to avoid double escaping in the
    # log message itself.
    record_json = records[-1].json
    assert isinstance(record_json, dict)
    payload = record_json.get("payload")
    assert payload
    assert payload["token"] == REDACTED
    assert payload["nested"]["password"] == REDACTED
    assert payload["list"][0]["api_key"] == REDACTED
    entry = json.loads(log_file.read_text().splitlines()[-1])
    assert entry["event"] == "TEST_DEBUG"
    assert entry["level"] == "DEBUG"
    assert entry["payload"]["token"] == REDACTED
    assert entry["payload"]["nested"]["password"] == REDACTED
    assert entry["payload"]["list"][0]["api_key"] == REDACTED


def test_log_debug_payload_does_not_accumulate_escape_sequences(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "debug.jsonl"
    handler = JsonlHandler(str(log_file))
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        log_debug_payload("TEST_ESC", {"text": "line1\nline2", "value": "\\"})
    finally:
        logger.setLevel(prev_level)
        logger.removeHandler(handler)
    line = log_file.read_text().splitlines()[-1]
    # Single escaping ("\\n") is expected from JSON encoding; double escaping
    # ("\\\\n") indicates we serialised an already-escaped string.
    assert "TEST_ESC" in line
    assert "\\n" in line
    assert "\\\\n" not in line
