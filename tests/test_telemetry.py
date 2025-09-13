import json
import logging
from pathlib import Path

import app.telemetry as telemetry
from app.log import JsonlHandler, logger
from app.telemetry import REDACTED, log_event, sanitize


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


def test_log_event_records_size_and_duration_and_sanitizes_payload(tmp_path: Path, monkeypatch) -> None:
    log_file = tmp_path / "telemetry.jsonl"
    handler = JsonlHandler(str(log_file))
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        monkeypatch.setattr(telemetry.time, "monotonic", lambda: 2.0)
        payload = {"token": "secret", "foo": "bar"}
        log_event("TEST_EVENT", payload, start_time=1.0)
    finally:
        logger.setLevel(prev_level)
        logger.removeHandler(handler)
    entry = json.loads(log_file.read_text().splitlines()[0])
    sanitized_payload = {"token": REDACTED, "foo": "bar"}
    expected_size = len(json.dumps(sanitized_payload, ensure_ascii=False).encode("utf-8"))
    assert entry["payload"] == sanitized_payload
    assert "secret" not in json.dumps(entry)
    assert entry["size_bytes"] == expected_size
    assert entry["duration_ms"] == 1000
