from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple

from ...core.doc_store import (
    Document,
    iter_links as doc_iter_links,
    load_documents,
    list_item_ids,
    load_item,
    save_item,
    item_path,
    rid_for,
    next_item_id as doc_next_item_id,
)
from ...core.model import Requirement, requirement_from_dict, requirement_to_dict
from ...core.labels import Label, _color_from_name


@dataclass
class DocumentsController:
    """Load documents and their items for the GUI."""

    root: Path
    model: object

    def __post_init__(self) -> None:
        self.documents: Dict[str, Document] = {}

    # ------------------------------------------------------------------
    def load_documents(self) -> Dict[str, Document]:
        """Populate ``documents`` from ``root`` and return them."""
        self.documents = load_documents(self.root)
        return self.documents

    def load_items(self, prefix: str) -> dict[int, list[int]]:
        """Load items for document ``prefix`` into the model.

        Returns a mapping of source requirement id to list of derived ids.
        """
        doc = self.documents.get(prefix)
        if not doc:
            self.model.set_requirements([])
            return {}
        directory = self.root / prefix
        items = []
        derived_map: dict[int, list[int]] = {}
        for item_id in sorted(list_item_ids(directory, doc)):
            data, _mtime = load_item(directory, doc, item_id)
            rid = rid_for(doc, item_id)
            req = requirement_from_dict(data, doc_prefix=doc.prefix, rid=rid)
            items.append(req)
            for link in getattr(req, "derived_from", []):
                derived_map.setdefault(link.source_id, []).append(req.id)
        self.model.set_requirements(items)
        return derived_map

    def collect_labels(self, prefix: str) -> tuple[list[Label], bool]:
        """Return labels and free-form flag for document ``prefix``.

        Aggregates label definitions from the selected document and all its
        ancestors while determining whether any document in the chain permits
        free-form labels.
        """

        labels: list[Label] = []
        allow_freeform = False
        chain: list[Document] = []
        current = self.documents.get(prefix)
        while current:
            chain.append(current)
            allow_freeform = allow_freeform or current.labels.allow_freeform
            if not current.parent:
                break
            current = self.documents.get(current.parent)
        for doc in reversed(chain):
            for ld in doc.labels.defs:
                color = ld.color or _color_from_name(ld.key)
                labels.append(Label(ld.key, color))
        return labels, allow_freeform

    # requirement operations -----------------------------------------
    def next_item_id(self, prefix: str) -> int:
        """Return next available requirement id for document ``prefix``."""

        doc = self.documents[prefix]
        return doc_next_item_id(self.root / prefix, doc)

    def add_requirement(self, prefix: str, req: Requirement) -> None:
        """Add ``req`` to the in-memory model for document ``prefix``."""

        doc = self.documents[prefix]
        req.doc_prefix = prefix
        req.rid = rid_for(doc, req.id)
        self.model.add(req)

    def save_requirement(self, prefix: str, req: Requirement) -> Path:
        """Persist ``req`` within document ``prefix`` and return file path."""

        doc = self.documents[prefix]
        req.doc_prefix = prefix
        req.rid = rid_for(doc, req.id)
        data = requirement_to_dict(req)
        return save_item(self.root / prefix, doc, data)

    def delete_requirement(self, prefix: str, req_id: int) -> bool:
        """Remove requirement ``req_id`` from document ``prefix``."""

        doc = self.documents.get(prefix)
        if not doc:
            return False
        path = item_path(self.root / prefix, doc, req_id)
        if path.exists():
            path.unlink()
        self.model.delete(req_id)
        return True

    # ------------------------------------------------------------------
    def iter_links(self) -> Iterable[Tuple[str, str]]:
        """Yield ``(child_rid, parent_rid)`` pairs for requirements."""

        return doc_iter_links(self.root)
