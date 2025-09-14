from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


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
