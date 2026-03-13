"""Tests for :class:`app.ui.main_frame.WxLogHandler`."""

import logging
from pathlib import Path
import time

import pytest

from app.ui.main_frame import WxLogHandler
from app.ui.main_frame import logging as logging_module

pytestmark = pytest.mark.unit


class _StubTextCtrl:
    """Minimal stub mimicking ``wx.TextCtrl`` interface for tests."""

    def __init__(self) -> None:
        self._buffer = ""

    def AppendText(self, text: str) -> None:  # pragma: no cover - not exercised
        self._buffer += text

    def GetLastPosition(self) -> int:  # pragma: no cover - not exercised
        return len(self._buffer)

    def Remove(self, start: int, end: int) -> None:  # pragma: no cover - not exercised
        del start, end

    def IsBeingDeleted(self) -> bool:  # pragma: no cover - not exercised
        return False


def test_wx_log_handler_format_includes_timestamp() -> None:
    """Formatter attached to handler should render human-friendly timestamp."""

    handler = WxLogHandler(_StubTextCtrl())
    formatter = handler.formatter
    assert formatter is not None
    formatter.converter = time.gmtime
    record = logging.LogRecord(
        name="cookareq",
        level=logging.INFO,
        pathname=__file__,
        lineno=42,
        msg="sample message",
        args=(),
        exc_info=None,
    )
    record.created = 0
    formatted = handler.format(record)
    assert formatted == "1970-01-01 00:00:00 INFO: sample message"


def test_read_text_log_tail_returns_last_segment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text_log = tmp_path / "cookareq.log"
    json_log = tmp_path / "cookareq.jsonl"
    text_log.write_text("0123456789", encoding="utf-8")

    monkeypatch.setattr(logging_module, "get_log_file_paths", lambda: (text_log, json_log))

    assert logging_module._read_text_log_tail(max_chars=4) == "6789"


def test_read_text_log_tail_returns_empty_when_file_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    missing = Path('/tmp/does-not-exist.log')
    monkeypatch.setattr(logging_module, "get_log_file_paths", lambda: (missing, missing.with_suffix('.jsonl')) )

    assert logging_module._read_text_log_tail(max_chars=500) == ""
