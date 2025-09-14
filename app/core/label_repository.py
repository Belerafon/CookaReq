"""Label repository interface and implementations."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from . import label_store
from .labels import Label


class LabelRepository(Protocol):
    """Abstract persistence operations for labels."""

    def load(self, directory: str | Path) -> list[Label]:
        """Load labels from *directory*."""

    def save(self, directory: str | Path, labels: list[Label]) -> Path:
        """Persist *labels* into *directory* and return resulting path."""


class FileLabelRepository(LabelRepository):
    """Filesystem-backed label repository."""

    def load(self, directory: str | Path) -> list[Label]:  # type: ignore[override]
        """Load labels from ``directory``."""

        return label_store.load_labels(directory)

    def save(self, directory: str | Path, labels: list[Label]) -> Path:  # type: ignore[override]
        """Persist ``labels`` into ``directory`` and return path."""

        return label_store.save_labels(directory, labels)
