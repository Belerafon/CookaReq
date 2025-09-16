from __future__ import annotations

import json
import re
from dataclasses import fields
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import jsonpatch

from ..model import Link, Requirement, requirement_fingerprint, requirement_from_dict, requirement_to_dict
from ..search import filter_by_labels, filter_by_status, search
from . import (
    Document,
    DocumentNotFoundError,
    RequirementNotFoundError,
    RequirementPage,
    RevisionMismatchError,
    ValidationError,
)
from .documents import load_documents, validate_labels

RID_RE = re.compile(r"^([A-Z][A-Z0-9_]*?)(\d+)$")
READ_ONLY_PATCH_FIELDS = {"id", "links"}
KNOWN_REQUIREMENT_FIELDS = {f.name for f in fields(Requirement)}


def _load_fingerprint_for_rid(
    root: Path,
    docs: Mapping[str, Document],
    rid: str,
    cache: dict[str, str | None],
) -> str | None:
    if rid in cache:
        return cache[rid]
    try:
        prefix, item_id = parse_rid(rid)
    except ValueError:
        cache[rid] = None
        return None
    doc = docs.get(prefix)
    if doc is None:
        cache[rid] = None
        return None
    path = root / prefix
    try:
        data, _ = load_item(path, doc, item_id)
    except FileNotFoundError:
        cache[rid] = None
        return None
    fingerprint = requirement_fingerprint(data)
    cache[rid] = fingerprint
    return fingerprint


def _prepare_links_for_storage(
    root: Path, docs: Mapping[str, Document], data: dict[str, Any]
) -> None:
    raw_links = data.get("links")
    if raw_links in (None, ""):
        data.pop("links", None)
        return
    if not isinstance(raw_links, list):
        raise ValidationError("links must be a list")
    cache: dict[str, str | None] = {}
    prepared: list[dict[str, Any]] = []
    for entry in raw_links:
        try:
            link = Link.from_raw(entry)
        except (TypeError, ValueError) as exc:
            raise ValidationError("invalid link entry") from exc
        fingerprint = _load_fingerprint_for_rid(root, docs, link.rid, cache)
        if fingerprint is None:
            link.suspect = True
        elif link.fingerprint is None:
            link.fingerprint = fingerprint
            link.suspect = False
        else:
            link.suspect = link.fingerprint != fingerprint
        prepared.append(link.to_dict())
    if prepared:
        prepared.sort(key=lambda item: item.get("rid", ""))
        data["links"] = prepared
    else:
        data.pop("links", None)


def _update_link_suspicions(
    root: Path,
    docs: Mapping[str, Document],
    req: Requirement,
    cache: dict[str, str | None] | None = None,
) -> None:
    if not req.links:
        return
    if cache is None:
        cache = {}
    for link in req.links:
        if not isinstance(link, Link):
            continue
        fingerprint = _load_fingerprint_for_rid(root, docs, link.rid, cache)
        if fingerprint is None:
            link.suspect = True
            continue
        if link.fingerprint is None:
            link.fingerprint = fingerprint
            link.suspect = False
        else:
            link.suspect = link.fingerprint != fingerprint


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def rid_for(doc: Document, item_id: int) -> str:
    """Return requirement identifier for ``item_id`` within ``doc``."""

    return f"{doc.prefix}{item_id:0{doc.digits}d}"


def _item_filename(doc: Document, item_id: int) -> str:
    return f"{item_id:0{doc.digits}d}.json"


def _legacy_item_filename(doc: Document, item_id: int) -> str:
    return f"{rid_for(doc, item_id)}.json"


def parse_rid(rid: str) -> tuple[str, int]:
    """Split ``rid`` into document prefix and numeric id."""

    match = RID_RE.match(rid)
    if not match:
        raise ValueError(f"invalid requirement id: {rid}")
    prefix, num = match.groups()
    return prefix, int(num)


def item_path(directory: str | Path, doc: Document, item_id: int) -> Path:
    """Return filesystem path for ``item_id`` inside ``doc`` using new naming."""

    directory_path = Path(directory)
    return directory_path / "items" / _item_filename(doc, item_id)


def locate_item_path(directory: str | Path, doc: Document, item_id: int) -> Path:
    """Return actual filesystem path for ``item_id`` supporting legacy layouts."""

    directory_path = Path(directory)
    new_path = item_path(directory_path, doc, item_id)
    if new_path.exists():
        return new_path
    legacy_path = directory_path / "items" / _legacy_item_filename(doc, item_id)
    if legacy_path.exists():
        return legacy_path
    return new_path


def save_item(directory: str | Path, doc: Document, data: dict) -> Path:
    """Save requirement ``data`` within ``doc`` and return file path."""

    root = Path(directory).parent
    docs = load_documents(root)
    from .links import validate_item_links  # local import to avoid cycle

<<<<<codex/remove-redundant-names-in-files
    validate_item_links(root, doc, data, docs)
    directory_path = Path(directory)
    item_id = int(data["id"])
    path = item_path(directory_path, doc, item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
    legacy_path = directory_path / "items" / _legacy_item_filename(doc, item_id)
    if legacy_path != path and legacy_path.exists():
        legacy_path.unlink()
====
    payload = dict(data)
    validate_item_links(root, doc, payload, docs)
    _prepare_links_for_storage(root, docs, payload)
    path = item_path(directory, doc, int(payload["id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
>>>>> m
    return path


def load_item(directory: str | Path, doc: Document, item_id: int) -> tuple[dict, float]:
    """Load requirement ``item_id`` from ``doc`` and return data with mtime."""

    path = locate_item_path(directory, doc, item_id)
    data = _read_json(path)
    mtime = path.stat().st_mtime
    return data, mtime


def list_item_ids(directory: str | Path, doc: Document) -> set[int]:
    """Return numeric ids of requirements present in ``doc``."""

    items_dir = Path(directory) / "items"
    ids: set[int] = set()
    if not items_dir.is_dir():
        return ids
    for fp in items_dir.glob("*.json"):
        stem = fp.stem
        if stem.startswith(doc.prefix):
            stem = stem[len(doc.prefix) :]
        try:
            ids.add(int(stem))
        except ValueError:
            continue
    return ids


def next_item_id(directory: str | Path, doc: Document) -> int:
    """Return the next available numeric id for ``doc``."""

    ids = list_item_ids(directory, doc)
    return max(ids, default=0) + 1


def _ensure_documents(root: Path, docs: Mapping[str, Document] | None) -> Mapping[str, Document]:
    return docs if docs is not None else load_documents(root)


def _iter_requirements(root: Path, docs: Mapping[str, Document]) -> list[Requirement]:
    requirements: list[Requirement] = []
    cache: dict[str, str | None] = {}
    for prefix, doc in docs.items():
        directory = root / prefix
        for item_id in sorted(list_item_ids(directory, doc)):
            data, _ = load_item(directory, doc, item_id)
            rid = rid_for(doc, item_id)
            cache[rid] = requirement_fingerprint(data)
            requirements.append(
                requirement_from_dict(
                    data,
                    doc_prefix=prefix,
                    rid=rid,
                )
            )
    for req in requirements:
        _update_link_suspicions(root, docs, req, cache)
    return requirements


def _normalize_labels(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (str, bytes)):
        raise ValidationError("labels must be a list of strings")
    if not isinstance(raw, Sequence):
        raise ValidationError("labels must be a list of strings")
    labels: list[str] = []
    for label in raw:
        if not isinstance(label, str):
            raise ValidationError("labels must be a list of strings")
        labels.append(label)
    return labels


def _paginate_requirements(
    requirements: Sequence[Requirement], page: int, per_page: int
) -> RequirementPage:
    page = 1 if page < 1 else page
    per_page = 1 if per_page < 1 else per_page
    items = list(requirements)
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    return RequirementPage(items=items[start:end], total=total, page=page, per_page=per_page)


def _resolve_requirement(
    root: Path, rid: str, docs: Mapping[str, Document]
) -> tuple[str, int, Document, Path, dict]:
    prefix, item_id = parse_rid(rid)
    doc = docs.get(prefix)
    if doc is None:
        raise RequirementNotFoundError(rid)
    directory = root / prefix
    try:
        data, _ = load_item(directory, doc, item_id)
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        raise RequirementNotFoundError(rid) from exc
    return prefix, item_id, doc, directory, data


def list_requirements(
    root: str | Path,
    *,
    page: int = 1,
    per_page: int = 50,
    status: str | None = None,
    labels: Sequence[str] | None = None,
    docs: Mapping[str, Document] | None = None,
) -> RequirementPage:
    root_path = Path(root)
    if docs is None and not root_path.is_dir():
        raise FileNotFoundError(root_path)
    docs_map = _ensure_documents(root_path, docs)
    requirements = _iter_requirements(root_path, docs_map)
    requirements = filter_by_status(requirements, status)
    requirements = filter_by_labels(requirements, list(labels or []))
    return _paginate_requirements(requirements, page, per_page)


def search_requirements(
    root: str | Path,
    *,
    query: str | None = None,
    labels: Sequence[str] | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 50,
    docs: Mapping[str, Document] | None = None,
) -> RequirementPage:
    root_path = Path(root)
    if docs is None and not root_path.is_dir():
        raise FileNotFoundError(root_path)
    docs_map = _ensure_documents(root_path, docs)
    all_requirements = _iter_requirements(root_path, docs_map)
    filtered = filter_by_status(all_requirements, status)
    filtered = search(filtered, labels=labels, query=query)
    return _paginate_requirements(filtered, page, per_page)


def get_requirement(
    root: str | Path,
    rid: str,
    *,
    docs: Mapping[str, Document] | None = None,
) -> Requirement:
    root_path = Path(root)
    docs_map = _ensure_documents(root_path, docs)
    prefix, item_id, doc, _directory, data = _resolve_requirement(root_path, rid, docs_map)
    req = requirement_from_dict(data, doc_prefix=prefix, rid=rid)
    _update_link_suspicions(root_path, docs_map, req)
    return req


def create_requirement(
    root: str | Path,
    *,
    prefix: str,
    data: Mapping[str, Any],
    docs: Mapping[str, Document] | None = None,
) -> Requirement:
    root_path = Path(root)
    docs_map = _ensure_documents(root_path, docs)
    doc = docs_map.get(prefix)
    if doc is None:
        raise DocumentNotFoundError(prefix)
    payload = dict(data)
    labels = _normalize_labels(payload.get("labels"))
    err = validate_labels(prefix, labels, docs_map)
    if err:
        raise ValidationError(err)
    payload["labels"] = labels
    directory = root_path / prefix
    item_id = next_item_id(directory, doc)
    payload["id"] = item_id
    if "revision" not in payload:
        payload["revision"] = 1
    req = requirement_from_dict(payload, doc_prefix=prefix, rid=rid_for(doc, item_id))
    _update_link_suspicions(root_path, docs_map, req)
    save_item(directory, doc, requirement_to_dict(req))
    return req


def _validate_patch_operations(patch: Sequence[Mapping[str, Any]]) -> None:
    for op in patch:
        for key in ("path", "from"):
            path = op.get(key)
            if not path:
                continue
            target = path.lstrip("/").split("/", 1)[0]
            if target in READ_ONLY_PATCH_FIELDS:
                raise ValidationError(f"field is read-only: {target}")
            if target and target not in KNOWN_REQUIREMENT_FIELDS:
                raise ValidationError(f"unknown field: {target}")


def patch_requirement(
    root: str | Path,
    rid: str,
    patch: Sequence[Mapping[str, Any]],
    *,
    expected_revision: int,
    docs: Mapping[str, Document] | None = None,
) -> Requirement:
    root_path = Path(root)
    docs_map = _ensure_documents(root_path, docs)
    prefix, item_id, doc, directory, data = _resolve_requirement(root_path, rid, docs_map)
    try:
        current = int(data.get("revision", 1))
    except (TypeError, ValueError) as exc:
        raise ValidationError("revision must be an integer") from exc
    if current <= 0:
        raise ValidationError("revision must be positive")
    if current != expected_revision:
        raise RevisionMismatchError(expected_revision, current)
    _validate_patch_operations(patch)
    try:
        updated = jsonpatch.apply_patch(data, patch, in_place=False)
    except jsonpatch.JsonPatchException as exc:
        raise ValidationError(str(exc)) from exc
    updated = dict(updated)
    updated["id"] = item_id
    labels = _normalize_labels(updated.get("labels"))
    err = validate_labels(prefix, labels, docs_map)
    if err:
        raise ValidationError(err)
    updated["labels"] = labels
    revision_value = updated.get("revision", current)
    try:
        revision = int(revision_value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("revision must be an integer") from exc
    if revision <= 0:
        raise ValidationError("revision must be positive")
    updated["revision"] = revision
    req = requirement_from_dict(updated, doc_prefix=prefix, rid=rid)
    _update_link_suspicions(root_path, docs_map, req)
    save_item(directory, doc, requirement_to_dict(req))
    return req


def delete_requirement(
    root: str | Path,
    rid: str,
    *,
    expected_revision: int,
    docs: Mapping[str, Document] | None = None,
) -> str:
    root_path = Path(root)
    docs_map = _ensure_documents(root_path, docs)
    _prefix, _item_id, _doc, _directory, data = _resolve_requirement(root_path, rid, docs_map)
    try:
        current = int(data.get("revision", 1))
    except (TypeError, ValueError) as exc:
        raise ValidationError("revision must be an integer") from exc
    if current <= 0:
        raise ValidationError("revision must be positive")
    if current != expected_revision:
        raise RevisionMismatchError(expected_revision, current)
    from .links import delete_item  # local import to avoid cycle

    deleted = delete_item(root_path, rid, docs_map)
    if not deleted:  # pragma: no cover - defensive
        raise RequirementNotFoundError(rid)
    return rid
