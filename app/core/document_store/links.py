from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..model import Link, Requirement, requirement_fingerprint, requirement_from_dict, requirement_to_dict
from . import Document, ValidationError
from .documents import is_ancestor, load_documents
from .items import (
    _ensure_documents,
    _update_link_suspicions,
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
        raise ValidationError("links: must be a list")
    for index, entry in enumerate(links):
        try:
            link = Link.from_raw(entry)
        except TypeError as exc:
            raise ValidationError(f"links[{index}]: {exc}") from exc
        except ValueError as exc:
            raise ValidationError(f"links[{index}]: {exc}") from exc
        rid = link.rid
        try:
            prefix, item_id = parse_rid(rid)
        except ValueError as exc:
            raise ValidationError(f"links[{index}].rid: {exc}") from exc
        if rid == rid_self:
            raise ValidationError(f"links[{index}]: link references self")
        target_doc = docs.get(prefix)
        if target_doc is None:
            raise ValidationError(
                f"links[{index}].rid: unknown document prefix: {prefix}"
            )
        if not is_ancestor(doc.prefix, prefix, docs):
            raise ValidationError(f"links[{index}].rid: invalid link target: {rid}")
        path = item_path(root / prefix, target_doc, item_id)
        if not path.exists():
            raise ValidationError(f"links[{index}].rid: linked item not found: {rid}")


def iter_links(root: str | Path) -> Iterable[tuple[str, str]]:
    """Yield pairs of (child_rid, parent_rid) for all links under ``root``."""

    docs = load_documents(root)
    for prefix in sorted(docs):
        doc = docs[prefix]
        directory = Path(root) / prefix
        for item_id in sorted(list_item_ids(directory, doc)):
            data, _ = load_item(directory, doc, item_id)
            rid = rid_for(doc, item_id)
            raw_links = data.get("links")
            if not isinstance(raw_links, list):
                continue
            parents: list[str] = []
            for entry in raw_links:
                try:
                    link = Link.from_raw(entry)
                except (TypeError, ValueError):  # pragma: no cover - defensive
                    continue
                parents.append(link.rid)
            for parent in sorted(parents):
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
            if not isinstance(links, list):
                continue
            for entry in links:
                try:
                    link = Link.from_raw(entry)
                except (TypeError, ValueError):  # pragma: no cover - defensive
                    continue
                if link.rid == rid:
                    affected.append(rid_for(d, other_id))
                    break
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
                    changed = True
                    continue
                new_links.append(link.to_dict())
            if changed:
                data["links"] = new_links
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
    docs: Mapping[str, Document] | None = None,
) -> Requirement:
    """Link ``derived_rid`` to ``source_rid`` when hierarchy permits."""

    if link_type != "parent":
        raise ValidationError(f"invalid link_type: {link_type}")

    root_path = Path(root)
    docs_map = _ensure_documents(root_path, docs)

    try:
        (
            source_prefix,
            _,
            _,
            _,
            source_data,
            source_canonical_rid,
        ) = _resolve_requirement(root_path, source_rid, docs_map)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValidationError(str(exc)) from exc

    try:
        (
            derived_prefix,
            _derived_id,
            derived_doc,
            derived_dir,
            data,
            derived_canonical_rid,
        ) = _resolve_requirement(root_path, derived_rid, docs_map)
    except ValueError as exc:  # pragma: no cover - defensive
        raise ValidationError(str(exc)) from exc

    if not is_ancestor(derived_prefix, source_prefix, docs_map):
        raise ValidationError(f"invalid link target: {source_canonical_rid}")

    try:
        current = int(data.get("revision", 1))
    except (TypeError, ValueError) as exc:
        raise ValidationError("revision must be an integer") from exc
    if current <= 0:
        raise ValidationError("revision must be positive")

    existing_raw = data.get("links")
    existing_links: dict[str, Link] = {}
    if existing_raw is not None:
        if not isinstance(existing_raw, list):
            raise ValidationError("links must be a list")
        for entry in existing_raw:
            try:
                link = Link.from_raw(entry)
            except (TypeError, ValueError) as exc:
                raise ValidationError("invalid link entry") from exc
            existing_links[link.rid] = link

    new_link = Link(
        rid=source_canonical_rid,
        fingerprint=requirement_fingerprint(source_data),
        suspect=False,
    )
    existing_links[source_canonical_rid] = new_link

    updated = dict(data)
    updated_links = [link.to_dict() for link in existing_links.values()]
    updated_links.sort(key=lambda item: item.get("rid", ""))
    updated["links"] = updated_links
    revision_value = updated.get("revision", current)
    try:
        revision = int(revision_value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("revision must be an integer") from exc
    if revision <= 0:
        raise ValidationError("revision must be positive")
    updated["revision"] = revision

    req = requirement_from_dict(
        updated,
        doc_prefix=derived_prefix,
        rid=derived_canonical_rid,
    )
    _update_link_suspicions(root_path, docs_map, req)
    save_item(derived_dir, derived_doc, requirement_to_dict(req))
    return req
