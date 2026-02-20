"""Read and persist document metadata stored alongside requirement files."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from ...i18n import _
from .types import Document, LabelDef, ValidationError


def _is_document_directory(path: Path) -> bool:
    """Return ``True`` when ``path`` looks like a single document directory."""
    return (path / "document.json").is_file() and (path / "items").is_dir()


def _contains_document_children(path: Path) -> bool:
    """Return ``True`` when ``path`` directly contains document directories."""
    children = [child for child in path.iterdir() if child.is_dir()]
    return any((child / "document.json").is_file() for child in children)


def _format_hint_path(path: Path, *, max_parts: int = 3) -> str:
    """Return compact path representation suited for message-box hints."""
    parts = [part for part in path.parts if part not in ("/", "")]
    if not parts:
        return path.anchor or str(path)
    if len(parts) <= max_parts:
        return str(path)
    return f"…/{'/'.join(parts[-max_parts:])}"


def diagnose_requirements_root(root: str | Path) -> str | None:
    """Return a human-friendly hint when ``root`` likely points to a wrong level.

    The expected root layout stores documents directly under ``root`` where each
    child contains ``document.json`` and an ``items`` directory. The helper only
    performs shallow checks so it can run quickly during folder selection.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        return None

    if root_path.name in {"items", "assets"} and _is_document_directory(root_path.parent):
        return _(
            "Selected folder "
            '"{selected}" is the "{nested}" subfolder of document "{document}"; '
            'open requirements root "{target}".'
        ).format(
            selected=_format_hint_path(root_path),
            nested=root_path.name,
            document=root_path.parent.name,
            target=_format_hint_path(root_path.parent.parent),
        )

    if root_path.name == ".cookareq" and _contains_document_children(root_path.parent):
        return _(
            'Selected folder "{selected}" stores internal CookaReq data; '
            'open parent folder "{target}".'
        ).format(
            selected=_format_hint_path(root_path),
            target=_format_hint_path(root_path.parent),
        )

    if _is_document_directory(root_path):
        return _(
            'Selected folder "{selected}" looks like a single document; '
            'open parent folder "{target}".'
        ).format(
            selected=_format_hint_path(root_path),
            target=_format_hint_path(root_path.parent),
        )

    children = [child for child in root_path.iterdir() if child.is_dir()]
    if any((child / "document.json").is_file() for child in children):
        return None

    descendants: list[Path] = []
    for child in children:
        if any((nested / "document.json").is_file() for nested in child.iterdir() if nested.is_dir()):
            descendants.append(child)

    if len(descendants) == 1:
        candidate = descendants[0]
        return _(
            'Selected folder "{selected}" is one level above requirements root; '
            'open "{target}".'
        ).format(selected=_format_hint_path(root_path), target=_format_hint_path(candidate))
    if len(descendants) > 1:
        options = ", ".join(f"'{path.name}'" for path in sorted(descendants))
        return _(
            'Selected folder "{selected}" is above several requirement roots ({options}); '
            "open the exact folder that directly contains document directories."
        ).format(selected=_format_hint_path(root_path), options=options)
    return None

def is_new_requirements_directory(root: str | Path) -> bool:
    """Return ``True`` when ``root`` looks like a fresh directory without documents."""
    root_path = Path(root)
    if not root_path.is_dir():
        return False
    if _is_document_directory(root_path):
        return False
    children = [child for child in root_path.iterdir() if child.is_dir()]
    if any((child / "document.json").is_file() for child in children):
        return False
    return not any(any((nested / "document.json").is_file() for nested in child.iterdir() if nested.is_dir()) for child in children)


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
    return Document.from_mapping(prefix=prefix, data=data)


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
        **doc.to_mapping(),
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
