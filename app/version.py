"""Helpers for reading the packaged application version."""

from __future__ import annotations

import json
import sys
from importlib import resources
from pathlib import Path


def load_version_date() -> str | None:
    """Return the build date from the packaged version metadata."""
    text = _load_version_text()
    if text is None:
        return None

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None
    raw = payload.get("date")
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    return cleaned or None


def _load_version_text() -> str | None:
    try:
        return (
            resources.files("app.resources")
            .joinpath("version.json")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        pass

    for candidate in _version_candidates():
        text = _read_text(candidate)
        if text is not None:
            return text
    return None


def _version_candidates() -> tuple[Path, ...]:
    module_base = Path(__file__).resolve().parent
    candidates = [module_base / "resources" / "version.json"]
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "app" / "resources" / "version.json")
    return tuple(candidates)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None
