"""Logging utilities for CookaReq."""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger("cookareq")

_log_dir: Path | None = None
_text_log_path: Path | None = None
_json_log_path: Path | None = None


class JsonlHandler(logging.Handler):
    """Write log records as JSON lines with timestamps."""

    def __init__(self, filename: Path | str) -> None:
        """Create handler writing JSON lines to *filename*."""
        super().__init__(level=logging.DEBUG)
        self.filename = Path(filename)

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - simple IO
        """Serialize ``record`` to JSONL with a timestamp."""

        data: Any = getattr(record, "json", None)
        if data is None:
            data = {"message": record.getMessage(), "level": record.levelname}
        if "timestamp" not in data:
            data["timestamp"] = utc_now_iso()
        self.filename.parent.mkdir(parents=True, exist_ok=True)
        with self.filename.open("a", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
            fh.write("\n")


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


def _rotate_log_file(path: Path, *, backups: int = _ROTATION_BACKUPS) -> None:
    """Rotate ``path`` preserving up to ``backups`` previous generations."""

    if backups <= 0:
        path.unlink(missing_ok=True)
        return

    for index in range(backups, 0, -1):
        rotated = path.with_name(f"{path.name}.{index}")
        source = path if index == 1 else path.with_name(f"{path.name}.{index - 1}")
        if not source.exists():
            continue
        if rotated.exists():
            rotated.unlink()
        source.rename(rotated)


def configure_logging(level: int = logging.INFO, *, log_dir: str | Path | None = None) -> None:
    """Configure application logger once."""

    global _log_dir, _text_log_path, _json_log_path

    if logger.handlers:
        if _log_dir is None:
            resolved_dir = _resolve_log_dir(log_dir).resolve()
            _log_dir = resolved_dir
            _text_log_path = resolved_dir / _TEXT_LOG_NAME
            _json_log_path = resolved_dir / _JSON_LOG_NAME
            _json_log_path.touch(exist_ok=True)
        return

    resolved_dir = _resolve_log_dir(log_dir).resolve()
    _log_dir = resolved_dir
    _text_log_path = resolved_dir / _TEXT_LOG_NAME
    _json_log_path = resolved_dir / _JSON_LOG_NAME

    _rotate_log_file(_text_log_path)
    _rotate_log_file(_json_log_path)
    _json_log_path.touch(exist_ok=True)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(_text_log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(file_handler)

    json_handler = JsonlHandler(_json_log_path)
    json_handler.setLevel(logging.DEBUG)
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

    if _text_log_path is None or _json_log_path is None:
        configure_logging()
    assert _text_log_path is not None
    assert _json_log_path is not None
    return _text_log_path, _json_log_path


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
