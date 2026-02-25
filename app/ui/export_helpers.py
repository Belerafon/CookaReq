"""Helpers for exporting requirements to disk."""

from __future__ import annotations

import shutil
from pathlib import Path


EXCEL_FRIENDLY_TEXT_SUFFIXES = frozenset({".csv", ".tsv"})


def text_export_encoding(path: Path) -> str:
    """Return encoding for text exports.

    CSV/TSV exports use UTF-8 BOM so Excel autodetects Unicode reliably
    on Windows locales with legacy ANSI defaults.
    """

    if path.suffix.lower() in EXCEL_FRIENDLY_TEXT_SUFFIXES:
        return "utf-8-sig"
    return "utf-8"


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
