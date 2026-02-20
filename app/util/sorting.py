"""Helpers for consistent sorting behavior."""

from __future__ import annotations

import re
from typing import Any

_NUMERIC_SPLIT = re.compile(r"(\d+)")


def natural_sort_key(value: Any) -> tuple[int, tuple[tuple[int, object], ...]]:
    """Return a natural sorting key for strings with numeric segments."""
    text = "" if value is None else str(value)
    text = text.strip()
    if not text:
        return (1, ())
    parts = _NUMERIC_SPLIT.split(text)
    key: list[tuple[int, object]] = []
    for part in parts:
        if not part:
            continue
        if part.isdigit():
            key.append((0, int(part)))
        else:
            key.append((1, part.casefold()))
    return (0, tuple(key))
