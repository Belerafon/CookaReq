from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..model import Requirement, requirement_from_dict, requirement_to_dict
from . import Document, RevisionMismatchError, ValidationError
from .documents import is_ancestor, load_documents
from .items import (
    _ensure_documents,
    _resolve_requirement,
    item_path,
    list_item_ids,
    load_item,
    parse_rid,
    rid_for,
    save_item,
)


def validate_item_links(
    root: Path, doc: Document, data: Mapping[str, Any], docs: Mapping[str, Document]
) -> None:
    rid_self = rid_for(doc, int(data["id"]))
    links = data.get("links")
    if links is None:
        return
    if not isinstance(links, list):
        raise ValidationError("links must be a list")
    for rid in links:
        try:
            prefix, item_id = parse_rid(rid)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        if rid == rid_self:
            raise ValidationError("link references self")
        target_doc = docs.get(prefix)
        if target_doc is None:
            raise ValidationError(f"unknown document prefix: {prefix}")
        if not is_ancestor(doc.prefix, prefix, docs):
            raise ValidationError(f"invalid link target: {rid}")
        path = item_path(root / prefix, target_doc, item_id)
        if not path.exists():
            raise ValidationError(f"linked item not found: {rid}")


def iter_links(root: str | Path) -> Iterable[tuple[str, str]]:
    """Yield pairs of (child_rid, parent_rid) for all links under ``root``."""

    docs = load_documents(root)
    for prefix in sorted(docs):
        doc = docs[prefix]
        directory = Path(root) / prefix
        for item_id in sorted(list_item_ids(directory, doc)):
            data, _ = load_item(directory, doc, item_id)
            rid = rid_for(doc, item_id)
            for parent in sorted(data.get("links", [])):
                yield rid, parent


def plan_delete_item(
    root: str | Path,
    rid: str,
    docs: Mapping[str, Document] | None = None,
) -> tuple[bool, list[str]]:
    """Return items referencing ``rid`` without deleting anything."""

    root_path = Path(root)
    if docs is None:
        docs = load_documents(root_path)
    try:
        prefix, item_id = parse_rid(rid)
    except ValueError:
        return False, []
    doc = docs.get(prefix)
    if doc is None:
        return False, []
    if not item_path(root_path / prefix, doc, item_id).exists():
        return False, []

    affected: list[str] = []
    for pfx, d in docs.items():
        dir_path = root_path / pfx
        for other_id in list_item_ids(dir_path, d):
            data, _ = load_item(dir_path, d, other_id)
            links = data.get("links")
            if isinstance(links, list) and rid in links:
                affected.append(rid_for(d, other_id))
    return True, sorted(affected)


def plan_delete_document(
    root: str | Path,
    prefix: str,
    docs: Mapping[str, Document] | None = None,
) -> tuple[list[str], list[str]]:
    """Return document prefixes and item ids that would be removed."""

    root_path = Path(root)
    if docs is None:
        docs = load_documents(root_path)
    doc = docs.get(prefix)
    if doc is None:
        return [], []

    docs_to_remove = [prefix]
    items: list[str] = []
    directory = root_path / prefix
    for item_id in list_item_ids(directory, doc):
        items.append(rid_for(doc, item_id))

    for pfx, d in docs.items():
        if d.parent == prefix:
            child_docs, child_items = plan_delete_document(root_path, pfx, docs)
            docs_to_remove.extend(child_docs)
            items.extend(child_items)
    return docs_to_remove, items


def delete_item(
    root: str | Path,
    rid: str,
    docs: Mapping[str, Document] | None = None,
) -> bool:
    """Remove requirement ``rid`` and drop links pointing to it."""

    root_path = Path(root)
    if docs is None:
        docs = load_documents(root_path)
    try:
        prefix, item_id = parse_rid(rid)
    except ValueError:
        return False
    doc = docs.get(prefix)
    if not doc:
        return False
    directory = root_path / prefix
    path = item_path(directory, doc, item_id)
    try:
        path.unlink()
    except FileNotFoundError:
        return False

    for pfx, d in docs.items():
        dir_path = root_path / pfx
        for other_id in list_item_ids(dir_path, d):
            data, _ = load_item(dir_path, d, other_id)
            links = data.get("links")
            if isinstance(links, list) and rid in links:
                data["links"] = [link for link in links if link != rid]
                save_item(dir_path, d, data)
    return True


def delete_document(
    root: str | Path,
    prefix: str,
    docs: Mapping[str, Document] | None = None,
) -> bool:
    """Remove document ``prefix`` and all its items."""

    root_path = Path(root)
    if docs is None:
        docs = load_documents(root_path)
    doc = docs.get(prefix)
    if doc is None:
        return False

    for pfx, d in list(docs.items()):
        if d.parent == prefix:
            delete_document(root_path, pfx, docs)

    directory = root_path / prefix
    for item_id in list(list_item_ids(directory, doc)):
        rid = rid_for(doc, item_id)
        delete_item(root_path, rid, docs)

    shutil.rmtree(directory, ignore_errors=True)
    docs.pop(prefix, None)
    return True


def link_requirements(
    root: str | Path,
    *,
    source_rid: str,
    derived_rid: str,
    link_type: str,
    expected_revision: int,
    docs: Mapping[str, Document] | None = None,
) -> Requirement:
    """Link ``derived_rid`` to ``source_rid`` when hierarchy permits."""

    if link_type != "parent":
        raise ValidationError(f"invalid link_type: {link_type}")

    root_path = Path(root)
    docs_map = _ensure_documents(root_path, docs)

    try:
        source_prefix, _source_id, _source_doc, _source_dir, _ = _resolve_requirement(
            root_path, source_rid, docs_map
        )
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValidationError(str(exc)) from exc

    try:
        derived_prefix, _derived_id, derived_doc, derived_dir, data = _resolve_requirement(
            root_path, derived_rid, docs_map
        )
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValidationError(str(exc)) from exc

    if not is_ancestor(derived_prefix, source_prefix, docs_map):
        raise ValidationError(f"invalid link target: {source_rid}")

    try:
        current = int(data.get("revision", 1))
    except (TypeError, ValueError) as exc:
        raise ValidationError("revision must be an integer") from exc
    if current <= 0:
        raise ValidationError("revision must be positive")
    if current != expected_revision:
        raise RevisionMismatchError(expected_revision, current)

    existing = data.get("links")
    if existing is None:
        existing_links: list[str] = []
    elif isinstance(existing, list):
        existing_links = [str(link) for link in existing]
    else:  # pragma: no cover - defensive
        raise ValidationError("links must be a list")

    updated = dict(data)
    updated["links"] = sorted(set(existing_links) | {source_rid})
    revision_value = updated.get("revision", current)
    try:
        revision = int(revision_value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("revision must be an integer") from exc
    if revision <= 0:
        raise ValidationError("revision must be positive")
    updated["revision"] = revision

    req = requirement_from_dict(updated, doc_prefix=derived_prefix, rid=derived_rid)
    save_item(derived_dir, derived_doc, requirement_to_dict(req))
    return req
