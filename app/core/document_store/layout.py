"""Helpers for working with canonical requirement item filenames."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

__all__ = [
    "canonical_item_name",
    "classify_item_path",
    "legacy_item_variants",
    "detect_legacy_layout",
]


def canonical_item_name(item_id: int) -> str:
    """Return canonical JSON filename for ``item_id``."""

    return f"{int(item_id)}.json"


def classify_item_path(path: Path, doc_prefix: str) -> tuple[int, bool] | None:
    """Classify ``path`` relative to ``doc_prefix``.

    Returns ``(item_id, is_canonical)`` when the filename encodes a requirement id.
    ``is_canonical`` is ``True`` only for files following the ``<id>.json`` pattern
    without zero padding or document prefixes. ``None`` indicates the file does not
    match any known requirement naming scheme.
    """

    stem = path.stem
    suffix = stem[len(doc_prefix) :] if stem.startswith(doc_prefix) else stem
    if not suffix or not suffix.isdigit():
        return None
    item_id = int(suffix)
    is_canonical = path.name == canonical_item_name(item_id)
    return item_id, is_canonical


def legacy_item_variants(
    items_dir: Path, doc_prefix: str, item_id: int
) -> list[Path]:
    """Return non-canonical files storing ``item_id`` inside ``items_dir``."""

    canonical = canonical_item_name(item_id)
    variants: list[Path] = []
    if not items_dir.is_dir():
        return variants
    for candidate in items_dir.glob("*.json"):
        classified = classify_item_path(candidate, doc_prefix)
        if not classified:
            continue
        candidate_id, is_canonical = classified
        if candidate_id != item_id or is_canonical:
            continue
        if candidate.name == canonical:
            continue
        variants.append(candidate)
    variants.sort()
    return variants


def detect_legacy_layout(items_dir: Path, doc_prefix: str) -> dict[int, list[Path]]:
    """Return mapping of requirement ids to legacy-named files."""

    legacy: dict[int, list[Path]] = defaultdict(list)
    if not items_dir.is_dir():
        return {}
    for candidate in items_dir.glob("*.json"):
        classified = classify_item_path(candidate, doc_prefix)
        if not classified:
            continue
        item_id, is_canonical = classified
        if is_canonical:
            continue
        legacy[item_id].append(candidate)
    if not legacy:
        return {}
    return {item_id: sorted(paths) for item_id, paths in legacy.items()}

