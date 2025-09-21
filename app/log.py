"""Logging utilities for CookaReq."""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .util.time import utc_now_iso

LOG_DIR_ENV = "COOKAREQ_LOG_DIR"
_DEFAULT_HOME_DIR = ".cookareq"
_DEFAULT_LOG_SUBDIR = "logs"
_TEXT_LOG_NAME = "cookareq.log"
_JSON_LOG_NAME = "cookareq.jsonl"
_ROTATION_BACKUPS = 5
_TEXT_LOG_MAX_BYTES = 5 * 1024 * 1024
_JSON_LOG_MAX_BYTES = 5 * 1024 * 1024

logger = logging.getLogger("cookareq")

_log_dir: Path | None = None


class JsonFormatter(logging.Formatter):
    """Convert log records into JSON strings."""

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        payload: Any = getattr(record, "json", None)
        if payload is None:
            data: dict[str, Any] = {
                "message": record.message,
                "level": record.levelname,
            }
        elif isinstance(payload, dict):
            data = dict(payload)
            data.setdefault("message", record.message)
            data.setdefault("level", record.levelname)
        else:
            data = {
                "message": record.message,
                "level": record.levelname,
                "data": payload,
            }
        if "timestamp" not in data:
            data["timestamp"] = utc_now_iso()
        if record.exc_info and "exc_info" not in data:
            data["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info and "stack_info" not in data:
            data["stack_info"] = self.formatStack(record.stack_info)
        return json.dumps(data, ensure_ascii=False)


class JsonlHandler(RotatingFileHandler):
    """Write log records as JSON lines with built-in rotation."""

    def __init__(
        self,
        filename: Path | str,
        *,
        max_bytes: int | None = None,
        backup_count: int = _ROTATION_BACKUPS,
        encoding: str = "utf-8",
        delay: bool = False,
    ) -> None:
        path = Path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        if max_bytes is None:
            max_bytes = _JSON_LOG_MAX_BYTES
        super().__init__(
            path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding=encoding,
            delay=delay,
        )
        self.setFormatter(JsonFormatter())


def _default_log_dir() -> Path:
    """Return default directory for application logs."""

    base = Path.home() / _DEFAULT_HOME_DIR
    return base / _DEFAULT_LOG_SUBDIR


def _resolve_log_dir(log_dir: str | Path | None) -> Path:
    """Resolve effective log directory creating it if necessary."""

    if log_dir is not None:
        path = Path(log_dir).expanduser()
    else:
        env_dir = os.environ.get(LOG_DIR_ENV)
        path = Path(env_dir).expanduser() if env_dir else _default_log_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def configure_logging(level: int = logging.INFO, *, log_dir: str | Path | None = None) -> None:
    """Configure application logger once."""

    global _log_dir

    if logger.handlers:
        if _log_dir is None:
            resolved_dir = _resolve_log_dir(log_dir).resolve()
            _log_dir = resolved_dir
        return

    resolved_dir = _resolve_log_dir(log_dir).resolve()
    _log_dir = resolved_dir

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(stream_handler)

    text_path = resolved_dir / _TEXT_LOG_NAME
    text_size = text_path.stat().st_size if text_path.exists() else 0
    file_handler = RotatingFileHandler(
        text_path,
        encoding="utf-8",
        maxBytes=_TEXT_LOG_MAX_BYTES,
        backupCount=_ROTATION_BACKUPS,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    if text_size > 0:
        file_handler.doRollover()
    logger.addHandler(file_handler)

    json_path = resolved_dir / _JSON_LOG_NAME
    json_size = json_path.stat().st_size if json_path.exists() else 0
    json_handler = JsonlHandler(
        json_path,
        backup_count=_ROTATION_BACKUPS,
    )
    json_handler.setLevel(logging.DEBUG)
    if json_size > 0:
        json_handler.doRollover()
    logger.addHandler(json_handler)

    logger.setLevel(logging.DEBUG)


def get_log_directory() -> Path:
    """Return directory where CookaReq writes log files."""

    if _log_dir is None:
        configure_logging()
    assert _log_dir is not None
    return _log_dir


def get_log_file_paths() -> tuple[Path, Path]:
    """Return paths to text and JSONL log files, configuring logging if needed."""

    if _log_dir is None:
        configure_logging()
    assert _log_dir is not None
    return _log_dir / _TEXT_LOG_NAME, _log_dir / _JSON_LOG_NAME


def open_log_directory() -> bool:
    """Open the log directory in the system file browser."""

    directory = get_log_directory()
    try:  # pragma: no cover - platform-dependent side effect
        if sys.platform.startswith("win"):
            os.startfile(str(directory))  # type: ignore[attr-defined]
            return True
        if sys.platform == "darwin":
            return subprocess.call(["open", str(directory)]) == 0
        return subprocess.call(["xdg-open", str(directory)]) == 0
    except Exception:  # pragma: no cover - best effort helper
        return False


__all__ = [
    "JsonlHandler",
    "configure_logging",
    "get_log_directory",
    "get_log_file_paths",
    "logger",
    "open_log_directory",
]
