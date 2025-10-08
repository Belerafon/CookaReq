from __future__ import annotations

import json
import re
from contextlib import suppress
from dataclasses import fields
from pathlib import Path
from typing import Any
from collections.abc import Callable, Mapping, Sequence

from ..model import (
    Link,
    Requirement,
    requirement_fingerprint,
    requirement_from_dict,
    requirement_to_dict,
)
from ..search import filter_by_labels, filter_by_status, search
from . import (
    Document,
    DocumentNotFoundError,
    RequirementIDCollisionError,
    RequirementNotFoundError,
    RequirementPage,
    ValidationError,
)
from .layout import canonical_item_name
from .documents import is_ancestor, load_documents, validate_labels

RID_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_]*?)(\d+)$")
KNOWN_REQUIREMENT_FIELDS = {f.name for f in fields(Requirement)}

EDITABLE_SINGLE_FIELDS = {
    "title",
    "statement",
    "type",
    "status",
    "owner",
    "priority",
    "source",
    "verification",
    "acceptance",
    "conditions",
    "rationale",
    "assumptions",
    "notes",
    "modified_at",
    "approved_at",
}

EDITABLE_COLLECTION_FIELDS = {
    "labels",
    "attachments",
    "links",
}

READ_ONLY_FIELDS = {
    "id",
    "revision",
    "doc_prefix",
    "rid",
}


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
    if "links" not in data:
        return
    raw_links = data["links"]
    if raw_links == []:
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
        canonical_rid = _canonical_rid(docs, link.rid)
        fingerprint = _load_fingerprint_for_rid(root, docs, link.rid, cache)
        if fingerprint is None:
            link.suspect = True
            if canonical_rid is not None:
                link.rid = canonical_rid
        elif link.fingerprint is None:
            link.fingerprint = fingerprint
            link.suspect = False
            if canonical_rid is not None:
                link.rid = canonical_rid
        else:
            link.suspect = link.fingerprint != fingerprint
            if canonical_rid is not None:
                link.rid = canonical_rid
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
        canonical_rid = _canonical_rid(docs, link.rid)
        fingerprint = _load_fingerprint_for_rid(root, docs, link.rid, cache)
        if fingerprint is None:
            link.suspect = True
            continue
        if canonical_rid is not None:
            link.rid = canonical_rid
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
    return f"{doc.prefix}{item_id}"


def _canonical_rid(docs: Mapping[str, Document], rid: str) -> str | None:
    try:
        prefix, item_id = parse_rid(rid)
    except ValueError:
        return None
    doc = docs.get(prefix)
    if doc is None:
        return None
    return rid_for(doc, item_id)


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
    return directory_path / "items" / canonical_item_name(item_id)


def save_item(directory: str | Path, doc: Document, data: dict) -> Path:
    """Save requirement ``data`` within ``doc`` and return file path."""
    root = Path(directory).parent
    docs = load_documents(root)
    from .links import validate_item_links  # local import to avoid cycle

    payload = dict(data)
    validate_item_links(root, doc, payload, docs)
    _prepare_links_for_storage(root, docs, payload)
    directory_path = Path(directory)
    item_id = int(payload["id"])
    path = item_path(directory_path, doc, item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return path


def load_item(directory: str | Path, doc: Document, item_id: int) -> tuple[dict, float]:
    """Load requirement ``item_id`` from ``doc`` and return data with mtime."""
    path = item_path(directory, doc, item_id)
    if not path.exists():
        raise FileNotFoundError(path)
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
        if not stem.isdigit():
            continue
        ids.add(int(stem))
    return ids


def next_item_id(directory: str | Path, doc: Document) -> int:
    """Return the next available numeric id for ``doc``."""
    ids = list_item_ids(directory, doc)
    return max(ids, default=0) + 1


def _ensure_documents(root: Path, docs: Mapping[str, Document] | None) -> Mapping[str, Document]:
    return docs if docs is not None else load_documents(root)


def _iter_requirements(
    root: Path,
    docs: Mapping[str, Document],
    *,
    all_docs: Mapping[str, Document] | None = None,
) -> list[Requirement]:
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
    doc_map = all_docs or docs
    for req in requirements:
        _update_link_suspicions(root, doc_map, req, cache)
    return requirements


def load_requirements(
    root: str | Path,
    *,
    prefixes: Sequence[str] | None = None,
    docs: Mapping[str, Document] | None = None,
) -> list[Requirement]:
    """Return requirements for the selected document prefixes.

    ``prefixes`` preserves the provided order and filters out duplicates. When
    omitted, requirements from *all* documents are returned. The function
    ensures that link metadata is refreshed (``Link.suspect`` reflects the
    current fingerprint state) in the same way as ``search_requirements`` and
    other high level helpers.
    """
    root_path = Path(root)
    if docs is None and not root_path.is_dir():
        raise FileNotFoundError(root_path)
    docs_map = _ensure_documents(root_path, docs)
    if prefixes is None:
        selected_order = sorted(docs_map)
    else:
        seen: set[str] = set()
        selected_order: list[str] = []
        for prefix in prefixes:
            if prefix not in docs_map:
                raise DocumentNotFoundError(prefix)
            if prefix in seen:
                continue
            seen.add(prefix)
            selected_order.append(prefix)
    selected_docs = {prefix: docs_map[prefix] for prefix in selected_order}
    return _iter_requirements(root_path, selected_docs, all_docs=docs_map)


def _normalize_labels(raw: Any) -> list[str]:
    if raw is None:
        raise ValidationError("labels must be a list of strings")
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
) -> tuple[str, int, Document, Path, dict, str]:
    prefix, item_id = parse_rid(rid)
    doc = docs.get(prefix)
    if doc is None:
        raise RequirementNotFoundError(rid)
    directory = root / doc.prefix
    try:
        data, _ = load_item(directory, doc, item_id)
    except FileNotFoundError as exc:  # pragma: no cover - defensive
        raise RequirementNotFoundError(rid) from exc
    canonical_rid = rid_for(doc, item_id)
    return doc.prefix, item_id, doc, directory, data, canonical_rid


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
    prefix, item_id, doc, _directory, data, canonical_rid = _resolve_requirement(
        root_path, rid, docs_map
    )
    req = requirement_from_dict(data, doc_prefix=prefix, rid=canonical_rid)
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
    labels = _normalize_labels(payload.get("labels", []))
    err = validate_labels(prefix, labels, docs_map)
    if err:
        raise ValidationError(err)
    payload["labels"] = labels
    directory = root_path / prefix
    item_id = next_item_id(directory, doc)
    payload["id"] = item_id
    if "revision" not in payload:
        payload["revision"] = 1
    try:
        req = requirement_from_dict(
            payload, doc_prefix=prefix, rid=rid_for(doc, item_id)
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    _update_link_suspicions(root_path, docs_map, req)
    save_item(directory, doc, requirement_to_dict(req))
    return req


def _next_revision(raw: Any) -> int:
    if raw in (None, ""):
        current = 1
    else:
        try:
            current = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError("revision must be an integer") from exc
    if current <= 0:
        raise ValidationError("revision must be positive")
    return current + 1


def _update_requirement(
    root: str | Path,
    rid: str,
    docs: Mapping[str, Document] | None,
    mutate: Callable[[dict[str, Any], str, Document], None],
) -> Requirement:
    root_path = Path(root)
    docs_map = _ensure_documents(root_path, docs)
    prefix, item_id, doc, directory, data, canonical_rid = _resolve_requirement(
        root_path, rid, docs_map
    )
    payload = dict(data)
    mutate(payload, prefix, doc)
    payload["id"] = item_id
    payload["revision"] = _next_revision(payload.get("revision"))
    labels = _normalize_labels(payload.get("labels", []))
    err = validate_labels(prefix, labels, docs_map)
    if err:
        raise ValidationError(err)
    payload["labels"] = labels
    try:
        req = requirement_from_dict(payload, doc_prefix=prefix, rid=canonical_rid)
    except (TypeError, ValueError) as exc:
        raise ValidationError(str(exc)) from exc
    _update_link_suspicions(root_path, docs_map, req)
    save_item(directory, doc, requirement_to_dict(req))
    return req


def update_requirement_field(
    root: str | Path,
    rid: str,
    *,
    field: str,
    value: Any,
    docs: Mapping[str, Document] | None = None,
) -> Requirement:
    if not isinstance(field, str) or not field:
        raise ValidationError("field must be a non-empty string")
    if field in READ_ONLY_FIELDS:
        raise ValidationError(f"field is read-only: {field}")
    if field in EDITABLE_COLLECTION_FIELDS:
        raise ValidationError(
            f"field {field} requires a dedicated collection update tool"
        )
    if field not in EDITABLE_SINGLE_FIELDS:
        if field not in KNOWN_REQUIREMENT_FIELDS:
            raise ValidationError(f"unknown field: {field}")
        raise ValidationError(f"field cannot be updated directly: {field}")

    def mutate(payload: dict[str, Any], _prefix: str, _doc: Document) -> None:
        payload[field] = value

    return _update_requirement(root, rid, docs, mutate)


def set_requirement_labels(
    root: str | Path,
    rid: str,
    labels: Sequence[str],
    *,
    docs: Mapping[str, Document] | None = None,
) -> Requirement:

    def mutate(payload: dict[str, Any], _prefix: str, _doc: Document) -> None:
        if not isinstance(labels, Sequence) or isinstance(labels, (str, bytes)):
            raise ValidationError("labels must be a list of strings")
        payload["labels"] = _normalize_labels(list(labels))

    return _update_requirement(root, rid, docs, mutate)


def set_requirement_attachments(
    root: str | Path,
    rid: str,
    attachments: Sequence[Mapping[str, Any]],
    *,
    docs: Mapping[str, Document] | None = None,
) -> Requirement:

    def mutate(payload: dict[str, Any], _prefix: str, _doc: Document) -> None:
        if not isinstance(attachments, Sequence) or isinstance(attachments, (str, bytes)):
            raise ValidationError("attachments must be a list")
        payload["attachments"] = list(attachments)

    return _update_requirement(root, rid, docs, mutate)


def set_requirement_links(
    root: str | Path,
    rid: str,
    links: Sequence[Mapping[str, Any] | str],
    *,
    docs: Mapping[str, Document] | None = None,
) -> Requirement:

    def mutate(payload: dict[str, Any], _prefix: str, _doc: Document) -> None:
        if not isinstance(links, Sequence) or isinstance(links, (str, bytes)):
            raise ValidationError("links must be a list")
        payload_links = list(links)
        if not payload_links:
            payload.pop("links", None)
        else:
            payload["links"] = payload_links

    return _update_requirement(root, rid, docs, mutate)


def move_requirement(
    root: str | Path,
    rid: str,
    *,
    new_prefix: str,
    payload: Mapping[str, Any] | None = None,
    docs: Mapping[str, Document] | None = None,
) -> Requirement:
    """Relocate requirement ``rid`` under ``new_prefix`` keeping referential integrity."""
    root_path = Path(root)
    docs_map = _ensure_documents(root_path, docs)
    (
        prefix,
        item_id,
        src_doc,
        src_directory,
        data,
        canonical_rid,
    ) = _resolve_requirement(root_path, rid, docs_map)
    rid = canonical_rid
    if new_prefix == prefix:
        raise ValidationError("requirement already belongs to the specified document")

    try:
        current_revision = int(data.get("revision", 1))
    except (TypeError, ValueError) as exc:
        raise ValidationError("revision must be an integer") from exc
    if current_revision <= 0:
        raise ValidationError("revision must be positive")

    dst_doc = docs_map.get(new_prefix)
    if dst_doc is None:
        raise DocumentNotFoundError(new_prefix)

    dst_dir = root_path / new_prefix
    new_id = next_item_id(dst_dir, dst_doc)
    new_rid = rid_for(dst_doc, new_id)
    dst_path = item_path(dst_dir, dst_doc, new_id)
    if dst_path.exists():
        raise RequirementIDCollisionError(new_prefix, new_id, rid=new_rid)

    updated_payload = dict(data)
    if payload is not None:
        updated_payload.update(payload)
    updated_payload["id"] = new_id
    if "revision" not in updated_payload or updated_payload["revision"] in (None, ""):
        updated_payload["revision"] = current_revision

    labels = _normalize_labels(updated_payload.get("labels", []))
    err = validate_labels(new_prefix, labels, docs_map)
    if err:
        raise ValidationError(err)
    updated_payload["labels"] = labels

    referencing_updates: list[tuple[Path, Document, dict[str, Any]]] = []
    for pfx, doc in docs_map.items():
        dir_path = root_path / pfx
        for other_id in list_item_ids(dir_path, doc):
            if pfx == prefix and other_id == item_id:
                continue
            item_data, _ = load_item(dir_path, doc, other_id)
            links = item_data.get("links")
            if not isinstance(links, list):
                continue
            changed = False
            new_links: list[dict[str, Any]] = []
            for entry in links:
                try:
                    link = Link.from_raw(entry)
                except (TypeError, ValueError):  # pragma: no cover - defensive
                    new_links.append(entry)
                    continue
                if link.rid == rid:
                    if not is_ancestor(doc.prefix, new_prefix, docs_map):
                        raise ValidationError(
                            
                                f"cannot move {rid}: link from {rid_for(doc, other_id)} would violate "
                                "document hierarchy"
                            
                        )
                    link.rid = new_rid
                    link.fingerprint = None
                    link.suspect = False
                    changed = True
                new_links.append(link.to_dict())
            if changed:
                updated = dict(item_data)
                updated["links"] = new_links
                referencing_updates.append((dir_path, doc, updated))

    req = requirement_from_dict(updated_payload, doc_prefix=new_prefix, rid=new_rid)
    _update_link_suspicions(root_path, docs_map, req)
    save_item(dst_dir, dst_doc, requirement_to_dict(req))

    for directory, doc, item_payload in referencing_updates:
        save_item(directory, doc, item_payload)

    src_path = item_path(src_directory, src_doc, item_id)
    with suppress(FileNotFoundError):  # pragma: no cover - defensive
        src_path.unlink()

    return req


def delete_requirement(
    root: str | Path,
    rid: str,
    *,
    docs: Mapping[str, Document] | None = None,
) -> str:
    root_path = Path(root)
    docs_map = _ensure_documents(root_path, docs)
    (
        _prefix,
        _item_id,
        _doc,
        _directory,
        data,
        canonical_rid,
    ) = _resolve_requirement(root_path, rid, docs_map)
    try:
        current = int(data.get("revision", 1))
    except (TypeError, ValueError) as exc:
        raise ValidationError("revision must be an integer") from exc
    if current <= 0:
        raise ValidationError("revision must be positive")
    from .links import delete_item  # local import to avoid cycle

    deleted = delete_item(root_path, canonical_rid, docs_map)
    if not deleted:  # pragma: no cover - defensive
        raise RequirementNotFoundError(canonical_rid)
    return canonical_rid
