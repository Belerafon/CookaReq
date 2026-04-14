"""Helpers for exporting a full requirements workspace as a ZIP archive."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile

from .document_store import Document, get_document_revision

__all__ = [
    "build_project_archive_name",
    "create_project_archive",
    "resolve_root_document_prefix",
]

_ARCHIVE_SUFFIX_RE = re.compile(r"(?:_rev\d+_\d{8})+$")


def resolve_root_document_prefix(
    docs: Mapping[str, Document],
    current_prefix: str | None,
) -> str | None:
    """Return top-level document prefix for ``current_prefix``."""
    if not current_prefix:
        return None
    current = docs.get(current_prefix)
    if current is None:
        return None
    seen: set[str] = set()
    while current.parent:
        if current.prefix in seen:
            return current.prefix
        seen.add(current.prefix)
        parent = docs.get(current.parent)
        if parent is None:
            break
        current = parent
    return current.prefix


def build_project_archive_name(
    *,
    project_dir: Path,
    docs: Mapping[str, Document],
    current_prefix: str | None,
    today: date | None = None,
) -> str:
    """Build default ZIP filename for the project archive export."""
    archive_date = today or date.today()
    root_prefix = resolve_root_document_prefix(docs, current_prefix)
    revision = 1
    if root_prefix:
        root_doc = docs.get(root_prefix)
        if root_doc is not None:
            revision = get_document_revision(root_doc)
    raw_name = project_dir.name.strip() or "requirements"
    safe_name = _ARCHIVE_SUFFIX_RE.sub("", raw_name).strip() or "requirements"
    return f"{safe_name}_rev{revision}_{archive_date:%Y%m%d}.zip"


def create_project_archive(
    *,
    project_dir: Path,
    output_path: Path,
) -> int:
    """Create ZIP archive with all files from ``project_dir``.

    Returns number of archived files.
    """
    project_root = project_dir.resolve()
    archive_path = output_path.resolve()

    files: list[Path] = []
    for path in sorted(project_root.rglob("*")):
        if not path.is_file():
            continue
        if path.resolve() == archive_path:
            continue
        files.append(path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, arcname=path.relative_to(project_root))
    return len(files)
