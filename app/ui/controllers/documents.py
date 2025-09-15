from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Tuple

from ...core.doc_store import (
    Document,
    LabelDef,
    collect_label_defs,
    iter_links as doc_iter_links,
    load_documents,
    list_item_ids,
    load_item,
    save_item,
    rid_for,
    next_item_id as doc_next_item_id,
    delete_document as doc_delete_document,
    delete_item,
)
from ...core.model import Requirement, requirement_from_dict, requirement_to_dict


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

    def load_items(self, prefix: str) -> dict[str, list[int]]:
        """Load items for document ``prefix`` into the model.

        Returns a mapping of parent requirement RID to list of linked item ids.
        """
        doc = self.documents.get(prefix)
        if not doc:
            self.model.set_requirements([])
            return {}
        directory = self.root / prefix
        items: list[Requirement] = []
        derived_map: dict[str, list[int]] = {}
        for item_id in sorted(list_item_ids(directory, doc)):
            data, _mtime = load_item(directory, doc, item_id)
            rid = rid_for(doc, item_id)
            req = requirement_from_dict(data, doc_prefix=doc.prefix, rid=rid)
            items.append(req)
            for parent in getattr(req, "links", []):
                derived_map.setdefault(parent, []).append(req.id)
        self.model.set_requirements(items)
        return derived_map

    def collect_labels(self, prefix: str) -> tuple[list[LabelDef], bool]:
        """Return labels and free-form flag for document ``prefix``."""

        return collect_label_defs(prefix, self.documents)

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
        rid = rid_for(doc, req_id)
        removed = delete_item(self.root, rid, self.documents)
        if removed:
            self.model.delete(req_id)
        return removed

    def delete_document(self, prefix: str) -> bool:
        """Remove document ``prefix`` and its descendants."""

        removed = doc_delete_document(self.root, prefix, self.documents)
        if removed:
            self.load_documents()
            self.model.set_requirements([])
        return removed

    # ------------------------------------------------------------------
    def iter_links(self) -> Iterable[Tuple[str, str]]:
        """Yield ``(child_rid, parent_rid)`` pairs for requirements."""

        return doc_iter_links(self.root)
