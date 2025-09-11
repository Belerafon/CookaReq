"""JSON file storage for requirements."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path

from app.util.hashing import id_to_hash
from .validate import validate


class ConflictError(Exception):
    """Raised when a file was modified on disk since loading."""


def filename_for(req_id: str, length: int = 12) -> str:
    """Return hashed filename for *req_id* with ``.json`` extension."""
    return f"{id_to_hash(req_id, length)}.json"


def load(path: str | Path) -> tuple[dict, float]:
    """Load requirement data from *path* and return data with its mtime."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    mtime = p.stat().st_mtime
    return data, mtime


def _existing_ids(directory: Path, exclude: Path) -> set[str]:
    ids: set[str] = set()
    for fp in directory.glob("*.json"):
        if fp == exclude:
            continue
        try:
            with fp.open("r", encoding="utf-8") as fh:
                ids.add(json.load(fh)["id"])
        except Exception:
            continue
    return ids


def save(
    directory: str | Path,
    data: dict | object,
    *,
    mtime: float | None = None,
    filename_length: int = 12,
) -> Path:
    """Save *data* into *directory* and return resulting path.

    Parameters
    ----------
    directory:
        Target directory for requirement files.
    data:
        Requirement data as ``dict`` or dataclass instance.
    mtime:
        Expected modification time of an existing file. If provided and the
        file's current mtime differs, :class:`ConflictError` is raised.
    filename_length:
        Length of hash used in filename generation.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    if is_dataclass(data):
        data = asdict(data)

    filename = filename_for(data["id"], length=filename_length)
    path = directory / filename

    validate(data, existing_ids=_existing_ids(directory, path))

    if path.exists() and mtime is not None:
        current = path.stat().st_mtime
        if current != mtime:
            raise ConflictError(f"file modified: {path}")

    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return path
