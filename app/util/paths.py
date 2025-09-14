"""Helpers for dealing with filesystem paths."""

from __future__ import annotations

from pathlib import Path


def ensure_relative(path: str | Path, base: str | Path) -> Path:
    """Return *path* relative to *base* or raise :class:`ValueError`.

    Both ``path`` and ``base`` are resolved before comparison.
    """
    abs_path = Path(path).expanduser().resolve()
    abs_base = Path(base).expanduser().resolve()
    try:
        return abs_path.relative_to(abs_base)
    except ValueError as exc:  # pragma: no cover - branch hit when raising
        raise ValueError(f"{abs_path} is not within {abs_base}") from exc
