"""Helpers for exporting requirements to disk."""

from __future__ import annotations

import shutil
from pathlib import Path


def prepare_export_destination(
    target_path: Path,
    *,
    assets_source: Path | None = None,
) -> Path:
    """Create an export directory and optionally copy assets next to the export file."""
    export_dir = target_path.parent / target_path.stem
    export_dir.mkdir(parents=True, exist_ok=True)

    if assets_source is not None and assets_source.is_dir():
        destination = export_dir / "assets"
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(assets_source, destination)

    return export_dir / target_path.name
