"""JSON file storage for requirements."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path

from app.log import logger

from .validate import validate
from .labels import Label
from .model import requirement_to_dict

LABELS_FILENAME = "labels.json"

# in-memory cache of requirement ids per directory
_ID_CACHE: dict[Path, set[int]] = {}


def _read_json(path: Path) -> object:
    """Read JSON from *path* and raise :class:`ValueError` on invalid content."""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


class ConflictError(Exception):
    """Raised when a file was modified on disk since loading."""


def filename_for(req_id: int) -> str:
    """Return filename for numeric *req_id* with ``.json`` extension."""
    return f"{req_id}.json"


def load(path: str | Path) -> tuple[dict, float]:
    """Load requirement data from *path* and return data with its mtime."""
    p = Path(path)
    data = _read_json(p)
    mtime = p.stat().st_mtime
    return data, mtime


def _scan_ids(directory: Path) -> set[int]:
    """Scan ``directory`` for requirement ids."""
    ids: set[int] = set()
    for fp in directory.glob("*.json"):
        if fp.name == LABELS_FILENAME:
            continue
        try:
            ids.add(_read_json(fp)["id"])
        except ValueError as exc:
            logger.warning("%s", exc)
            continue
        except Exception as exc:
            logger.warning("Failed to read %s: %s", fp, exc)
            continue
    return ids


def load_index(directory: str | Path) -> set[int]:
    """Return cached ids for ``directory``, loading once if needed."""
    path = Path(directory)
    ids = _ID_CACHE.get(path)
    if ids is None:
        ids = _scan_ids(path)
        _ID_CACHE[path] = ids
    return ids


def add_to_index(directory: str | Path, req_id: int) -> None:
    """Add ``req_id`` to cache for ``directory``."""
    load_index(directory).add(req_id)


def remove_from_index(directory: str | Path, req_id: int) -> None:
    """Remove ``req_id`` from cache for ``directory``."""
    ids = _ID_CACHE.get(Path(directory))
    if ids is not None:
        ids.discard(req_id)


def clear_index(directory: str | Path) -> None:
    """Drop cached ids for ``directory``."""
    _ID_CACHE.pop(Path(directory), None)


def save(
    directory: str | Path,
    data: dict | object,
    *,
    mtime: float | None = None,
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
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    if is_dataclass(data):
        data = requirement_to_dict(data)

    filename = filename_for(data["id"])
    path = directory / filename

    ids = load_index(directory)
    existing_ids = set(ids)
    existing_ids.discard(data["id"])
    validate(data, directory, existing_ids=existing_ids)

    if path.exists() and mtime is not None:
        current = path.stat().st_mtime
        if current != mtime:
            raise ConflictError(f"file modified: {path}")

    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
    add_to_index(directory, data["id"])
    try:
        mark_suspects(directory, data["id"], data.get("revision", 0))
    except Exception as exc:
        logger.warning("mark_suspects failed for %s: %s", data["id"], exc)
    return path


def delete(directory: str | Path, req_id: int) -> None:
    """Remove requirement ``req_id`` from ``directory`` and update cache."""
    directory = Path(directory)
    path = directory / filename_for(req_id)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    remove_from_index(directory, req_id)


def mark_suspects(directory: str | Path, changed_id: int, new_revision: int) -> None:
    """Mark referencing requirements as suspect when a source revision changes."""
    directory = Path(directory)
    for fp in directory.glob("*.json"):
        if fp.name == LABELS_FILENAME:
            continue
        try:
            data = _read_json(fp)
        except ValueError as exc:
            logger.warning("%s", exc)
            continue
        except Exception as exc:
            logger.warning("Failed to read %s: %s", fp, exc)
            continue
        changed = False
        parent = data.get("parent")
        if (
            parent
            and parent.get("source_id") == changed_id
            and parent.get("source_revision") != new_revision
            and not parent.get("suspect", False)
        ):
            parent["suspect"] = True
            changed = True

        for link in data.get("derived_from", []):
            if (
                link.get("source_id") == changed_id
                and link.get("source_revision") != new_revision
                and not link.get("suspect", False)
            ):
                link["suspect"] = True
                changed = True

        links_obj = data.get("links", {})
        for coll in (links_obj.get("verifies", []), links_obj.get("relates", [])):
            for link in coll:
                if (
                    link.get("source_id") == changed_id
                    and link.get("source_revision") != new_revision
                    and not link.get("suspect", False)
                ):
                    link["suspect"] = True
                    changed = True
        if changed:
            with fp.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# label storage


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
