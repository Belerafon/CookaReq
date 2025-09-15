from __future__ import annotations

import json
import re
import shutil
from hashlib import sha256
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass
class LabelDef:
    """Definition of a label available to document items."""

    key: str
    title: str
    color: str | None = None


def stable_color(name: str) -> str:
    """Return a pastel color generated from ``name``."""

    digest = sha256(name.encode("utf-8")).hexdigest()
    r = (int(digest[0:2], 16) + 0xAA) // 2
    g = (int(digest[2:4], 16) + 0xAA) // 2
    b = (int(digest[4:6], 16) + 0xAA) // 2
    return f"#{r:02x}{g:02x}{b:02x}"


def label_color(label: LabelDef) -> str:
    """Return explicit label color or a generated one."""

    return label.color or stable_color(label.key)


@dataclass
class DocumentLabels:
    """Label configuration for a document."""

    allow_freeform: bool = False
    defs: list[LabelDef] = field(default_factory=list)


@dataclass
class Document:
    """Configuration describing a document in the hierarchy."""

    prefix: str
    title: str
    digits: int
    parent: str | None = None
    labels: DocumentLabels = field(default_factory=DocumentLabels)
    attributes: dict[str, Any] = field(default_factory=dict)


class ValidationError(Exception):
    """Raised when requirement links violate business rules."""


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_document(directory: str | Path) -> Document:
    """Load document configuration from ``directory``."""

    path = Path(directory) / "document.json"
    data = _read_json(path)
    labels_data = data.get("labels", {})
    defs = [LabelDef(**d) for d in labels_data.get("defs", [])]
    labels = DocumentLabels(
        allow_freeform=labels_data.get("allowFreeform", False),
        defs=defs,
    )
    return Document(
        prefix=data["prefix"],
        title=data.get("title", data["prefix"]),
        digits=int(data["digits"]),
        parent=data.get("parent"),
        labels=labels,
        attributes=dict(data.get("attributes", {})),
    )


def save_document(directory: str | Path, doc: Document) -> Path:
    """Persist ``doc`` configuration into ``directory``."""

    path = Path(directory) / "document.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "prefix": doc.prefix,
        "title": doc.title,
        "digits": doc.digits,
        "parent": doc.parent,
        "labels": {
            "allowFreeform": doc.labels.allow_freeform,
            "defs": [asdict(d) for d in doc.labels.defs],
        },
        "attributes": doc.attributes,
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return path


def load_documents(root: str | Path) -> dict[str, Document]:
    """Load all document configurations under ``root``.

    Returns mapping of document prefix to :class:`Document` instance.
    Missing directories yield an empty mapping.
    """

    root_path = Path(root)
    docs: dict[str, Document] = {}
    if not root_path.is_dir():
        return docs
    for path in root_path.iterdir():
        doc_file = path / "document.json"
        if doc_file.is_file():
            doc = load_document(path)
            docs[doc.prefix] = doc
    return docs


def is_ancestor(
    child_prefix: str, ancestor_prefix: str, docs: Mapping[str, Document]
) -> bool:
    """Return ``True`` if ``ancestor_prefix`` is an ancestor of ``child_prefix``."""

    current = docs.get(child_prefix)
    while current and current.parent:
        if current.parent == ancestor_prefix:
            return True
        current = docs.get(current.parent)
    return False


def collect_label_defs(
    prefix: str, docs: Mapping[str, Document]
) -> tuple[list[LabelDef], bool]:
    """Return label definitions and freeform flag for ``prefix``.

    Aggregates label definitions from ``prefix`` and its ancestors while also
    determining whether any document in the chain permits free-form labels.
    Colors are resolved using :func:`label_color`.
    """

    labels: list[LabelDef] = []
    allow_freeform = False
    chain: list[Document] = []
    current = docs.get(prefix)
    while current:
        chain.append(current)
        allow_freeform = allow_freeform or current.labels.allow_freeform
        if not current.parent:
            break
        current = docs.get(current.parent)
    for doc in reversed(chain):
        for ld in doc.labels.defs:
            labels.append(LabelDef(ld.key, ld.title, label_color(ld)))
    return labels, allow_freeform


def collect_labels(prefix: str, docs: Mapping[str, Document]) -> tuple[set[str], bool]:
    """Return allowed label keys and freeform flag for ``prefix``."""

    defs, freeform = collect_label_defs(prefix, docs)
    return {d.key for d in defs}, freeform


def rid_for(doc: Document, item_id: int) -> str:
    """Return requirement identifier for ``item_id`` within ``doc``."""

    return f"{doc.prefix}{item_id:0{doc.digits}d}"


RID_RE = re.compile(r"^([A-Z][A-Z0-9_]*?)(\d+)$")


def parse_rid(rid: str) -> tuple[str, int]:
    """Split ``rid`` into document prefix and numeric id."""

    match = RID_RE.match(rid)
    if not match:
        raise ValueError(f"invalid requirement id: {rid}")
    prefix, num = match.groups()
    return prefix, int(num)


def _validate_links(
    root: Path,
    doc: Document,
    data: Mapping[str, Any],
    docs: Mapping[str, Document],
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


def item_path(directory: str | Path, doc: Document, item_id: int) -> Path:
    """Return filesystem path for ``item_id`` inside ``doc``."""

    return Path(directory) / "items" / f"{rid_for(doc, item_id)}.json"


def save_item(directory: str | Path, doc: Document, data: dict) -> Path:
    """Save requirement ``data`` within ``doc`` and return file path."""
    root = Path(directory).parent
    docs = load_documents(root)
    _validate_links(root, doc, data, docs)
    path = item_path(directory, doc, int(data["id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
    return path


def load_item(directory: str | Path, doc: Document, item_id: int) -> tuple[dict, float]:
    """Load requirement ``item_id`` from ``doc`` and return data with mtime."""

    path = item_path(directory, doc, item_id)
    data = _read_json(path)
    mtime = path.stat().st_mtime
    return data, mtime


def list_item_ids(directory: str | Path, doc: Document) -> set[int]:
    """Return numeric ids of requirements present in ``doc``."""

    items_dir = Path(directory) / "items"
    ids: set[int] = set()
    if not items_dir.is_dir():
        return ids
    for fp in items_dir.glob(f"{doc.prefix}*.json"):
        try:
            ids.add(int(fp.stem[len(doc.prefix):]))
        except ValueError:
            continue
    return ids


def next_item_id(directory: str | Path, doc: Document) -> int:
    """Return the next available numeric id for ``doc``."""

    ids = list_item_ids(directory, doc)
    return max(ids, default=0) + 1


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
    """Remove requirement ``rid`` and drop links pointing to it.

    Parameters
    ----------
    root:
        Directory containing requirement documents.
    rid:
        Identifier of the requirement to delete (e.g. ``"SYS001"``).
    docs:
        Optional pre-loaded document mapping to avoid repeated disk access.

    Returns
    -------
    bool
        ``True`` when the requirement existed and was removed.
    """

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

    # remove references from other requirements ---------------------
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
    """Remove document ``prefix`` and all its items.

    Deletion is recursive: child documents are removed prior to the target
    document. References to any removed items are also cleared from remaining
    requirements.
    """

    root_path = Path(root)
    if docs is None:
        docs = load_documents(root_path)
    doc = docs.get(prefix)
    if doc is None:
        return False

    # delete child documents first
    for pfx, d in list(docs.items()):
        if d.parent == prefix:
            delete_document(root_path, pfx, docs)

    # delete items and clean links
    directory = root_path / prefix
    for item_id in list(list_item_ids(directory, doc)):
        rid = rid_for(doc, item_id)
        delete_item(root_path, rid, docs)

    # remove document directory
    shutil.rmtree(directory, ignore_errors=True)
    docs.pop(prefix, None)
    return True
