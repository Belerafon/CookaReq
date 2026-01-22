"""Helpers for reading the packaged application version."""

from __future__ import annotations

import json
from importlib import resources


def load_version_date() -> str | None:
    """Return the build date from the packaged version metadata."""
    try:
        text = (
            resources.files("app.resources")
            .joinpath("version.json")
            .read_text(encoding="utf-8")
        )
    except FileNotFoundError:
        return None
    except OSError:
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
