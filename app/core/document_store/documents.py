from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from collections.abc import Mapping

from . import Document, DocumentLabels, LabelDef, ValidationError


def _read_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def stable_color(name: str) -> str:
    """Return a pastel color generated from ``name``."""
    from hashlib import sha256

    digest = sha256(name.encode("utf-8")).hexdigest()
    r = (int(digest[0:2], 16) + 0xAA) // 2
    g = (int(digest[2:4], 16) + 0xAA) // 2
    b = (int(digest[4:6], 16) + 0xAA) // 2
    return f"#{r:02x}{g:02x}{b:02x}"


def label_color(label: LabelDef) -> str:
    """Return explicit label color or a generated one."""
    return label.color or stable_color(label.key)


def load_document(directory: str | Path) -> Document:
    """Load document configuration from ``directory``."""
    directory_path = Path(directory)
    prefix = directory_path.name
    path = directory_path / "document.json"
    data = _read_json(path)
    stored_prefix = data.get("prefix")
    if stored_prefix is not None and stored_prefix != prefix:
        raise ValidationError(
            f"document prefix mismatch: directory '{prefix}' != stored '{stored_prefix}'"
        )
    labels_data = data.get("labels", {})
    defs = [LabelDef(**d) for d in labels_data.get("defs", [])]
    labels = DocumentLabels(
        allow_freeform=labels_data.get("allowFreeform", False),
        defs=defs,
    )
    return Document(
        prefix=prefix,
        title=data.get("title", prefix),
        parent=data.get("parent"),
        labels=labels,
        attributes=dict(data.get("attributes", {})),
    )


def save_document(directory: str | Path, doc: Document) -> Path:
    """Persist ``doc`` configuration into ``directory``."""
    directory_path = Path(directory)
    expected_prefix = directory_path.name
    if doc.prefix != expected_prefix:
        raise ValidationError(
            f"document prefix mismatch: directory '{expected_prefix}' != document '{doc.prefix}'"
        )
    path = directory_path / "document.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "title": doc.title,
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
    """Load all document configurations under ``root``."""
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
    if child_prefix == ancestor_prefix:
        return True
    current = docs.get(child_prefix)
    while current and current.parent:
        if current.parent == ancestor_prefix:
            return True
        current = docs.get(current.parent)
    return False


def collect_label_defs(
    prefix: str, docs: Mapping[str, Document]
) -> tuple[list[LabelDef], bool]:
    """Return label definitions and freeform flag for ``prefix``."""
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


def validate_labels(
    prefix: str, labels: list[str], docs: Mapping[str, Document]
) -> str | None:
    """Validate ``labels`` for items under document ``prefix``."""
    allowed, freeform = collect_labels(prefix, docs)
    if labels and not freeform:
        unknown = [lbl for lbl in labels if lbl not in allowed]
        if unknown:
            return f"unknown label: {unknown[0]}"
    return None
