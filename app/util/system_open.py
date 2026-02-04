"""Helpers for opening system folders in the default file browser."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_directory(directory: Path) -> bool:
    """Open ``directory`` in the system file browser."""
    try:
        resolved = directory.resolve()
    except OSError:
        resolved = directory
    try:  # pragma: no cover - platform-dependent side effect
        if sys.platform.startswith("win"):
            os.startfile(str(resolved))  # type: ignore[attr-defined]
            return True
        if sys.platform == "darwin":
            return subprocess.call(["open", str(resolved)]) == 0
        return subprocess.call(["xdg-open", str(resolved)]) == 0
    except Exception:  # pragma: no cover - best effort helper
        return False
