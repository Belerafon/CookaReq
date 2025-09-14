"""JSON file storage for label data."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from ..log import logger

from .labels import Label

LABELS_FILENAME = "labels.json"


def _read_json(path: Path) -> object:
    """Read JSON from *path* and raise :class:`ValueError` on invalid content."""
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def load_labels(directory: str | Path) -> list[Label]:
    """Load labels from ``directory``.

    Missing files yield an empty list.
    """
    path = Path(directory) / LABELS_FILENAME
    if not path.exists():
        return []
    try:
        data = _read_json(path)
    except ValueError as exc:
        logger.warning("%s", exc)
        return []
    return [Label(**item) for item in data]


def save_labels(directory: str | Path, labels: list[Label]) -> Path:
    """Persist ``labels`` into ``directory`` and return resulting path."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / LABELS_FILENAME
    with path.open("w", encoding="utf-8") as fh:
        json.dump([asdict(lbl) for lbl in labels], fh, ensure_ascii=False, indent=2, sort_keys=True)
    return path
