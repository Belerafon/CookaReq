"""Logging utilities for CookaReq."""

from __future__ import annotations

import json
import logging
from typing import Any

from .util.time import utc_now_iso

logger = logging.getLogger("cookareq")


class JsonlHandler(logging.Handler):
    """Write log records as JSON lines with timestamps."""

    def __init__(self, filename: str) -> None:
        super().__init__(level=logging.INFO)
        self.filename = filename

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - simple IO
        """Serialize ``record`` to JSONL with a timestamp."""

        data: Any = getattr(record, "json", None)
        if data is None:
            data = {"message": record.getMessage(), "level": record.levelname}
        if "timestamp" not in data:
            data["timestamp"] = utc_now_iso()
        with open(self.filename, "a", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
            fh.write("\n")


def configure_logging(level: int = logging.INFO) -> None:
    """Configure application logger once."""

    if logger.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)


__all__ = ["logger", "configure_logging", "JsonlHandler"]

