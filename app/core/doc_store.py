from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass
class LabelDef:
    """Definition of a label available to document items."""

    key: str
    title: str
    color: str | None = None


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


def item_path(directory: str | Path, doc: Document, item_id: int) -> Path:
    """Return filesystem path for ``item_id`` inside ``doc``."""

    return Path(directory) / "items" / f"{rid_for(doc, item_id)}.json"


def save_item(directory: str | Path, doc: Document, data: dict) -> Path:
    """Save requirement ``data`` within ``doc`` and return file path."""

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
