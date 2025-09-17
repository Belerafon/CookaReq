"""Tests for :class:`app.ui.main_frame.WxLogHandler`."""

import logging
import time

import pytest

from app.ui.main_frame import WxLogHandler

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
