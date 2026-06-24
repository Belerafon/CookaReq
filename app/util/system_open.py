"""Helpers for opening files and folders with the operating system."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _resolve_best_effort(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def open_path(path: Path) -> bool:
    """Open ``path`` with the platform default handler."""
    resolved = _resolve_best_effort(path)
    try:  # pragma: no cover - platform-dependent side effect
        if sys.platform.startswith("win"):
            os.startfile(str(resolved))  # type: ignore[attr-defined]
            return True
        if sys.platform == "darwin":
            return subprocess.call(["open", str(resolved)]) == 0
        return subprocess.call(["xdg-open", str(resolved)]) == 0
    except Exception:  # pragma: no cover - best effort helper
        return False


def open_file(file_path: Path) -> bool:
    """Open ``file_path`` in the default application."""
    return open_path(file_path)


def open_directory(directory: Path) -> bool:
    """Open ``directory`` in the system file browser."""
    return open_path(directory)


def reveal_in_file_manager(file_path: Path) -> bool:
    """Open the file manager and select ``file_path`` when the platform supports it."""
    resolved = _resolve_best_effort(file_path)
    try:  # pragma: no cover - platform-dependent side effect
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(resolved)])
            return True
        if sys.platform == "darwin":
            return subprocess.call(["open", "-R", str(resolved)]) == 0
        directory = resolved.parent if resolved.parent else Path(".")
        # xdg-open has no cross-desktop "select this file" flag; opening the
        # containing directory is the reliable Linux fallback.
        return subprocess.call(["xdg-open", str(directory)]) == 0
    except Exception:  # pragma: no cover - best effort helper
        return False
