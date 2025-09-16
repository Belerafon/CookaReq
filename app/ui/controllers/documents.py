from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Dict, Iterable, Tuple

from ...core.document_store import (
    Document,
    LabelDef,
    RequirementIDCollisionError,
    collect_label_defs,
    iter_links as doc_iter_links,
    load_documents,
    list_item_ids,
    load_item,
    parse_rid,
    save_document,
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

    _PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

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

    # helpers ---------------------------------------------------------
    @staticmethod
    def _parse_original_id(doc: Document, rid: str | None) -> int | None:
        if not rid:
            return None
        try:
            prefix, item_id = parse_rid(rid)
        except ValueError:
            return None
        if prefix != doc.prefix:
            return None
        return item_id

    def _ensure_unique_id(
        self,
        prefix: str,
        doc: Document,
        req: Requirement,
        *,
        original_id: int | None = None,
        original_rid: str | None = None,
    ) -> None:
        directory = self.root / prefix
        existing_ids = set(list_item_ids(directory, doc))
        if original_id is not None:
            existing_ids.discard(original_id)
        if req.id in existing_ids:
            raise RequirementIDCollisionError(prefix, req.id, rid=rid_for(doc, req.id))

        target_rid = original_rid or ""
        for existing in self.model.get_all():
            existing_prefix = getattr(existing, "doc_prefix", prefix) or prefix
            if existing_prefix != prefix:
                continue
            if existing is req:
                continue
            existing_rid = getattr(existing, "rid", "") or rid_for(doc, existing.id)
            if target_rid and existing_rid == target_rid:
                continue
            if (
                original_id is not None
                and req.id == original_id
                and existing.id == original_id
                and existing_rid == target_rid
            ):
                continue
            if existing.id == req.id:
                raise RequirementIDCollisionError(prefix, req.id, rid=rid_for(doc, req.id))

    # requirement operations -----------------------------------------
    def next_item_id(self, prefix: str) -> int:
        """Return next available requirement id for document ``prefix``."""

        doc = self.documents[prefix]
        return doc_next_item_id(self.root / prefix, doc)

    def add_requirement(self, prefix: str, req: Requirement) -> None:
        """Add ``req`` to the in-memory model for document ``prefix``."""

        doc = self.documents[prefix]
        self._ensure_unique_id(prefix, doc, req)
        req.doc_prefix = prefix
        req.rid = rid_for(doc, req.id)
        self.model.add(req)

    def save_requirement(self, prefix: str, req: Requirement) -> Path:
        """Persist ``req`` within document ``prefix`` and return file path."""

        doc = self.documents[prefix]
        original_rid = getattr(req, "rid", "")
        original_id = self._parse_original_id(doc, original_rid)
        self._ensure_unique_id(
            prefix,
            doc,
            req,
            original_id=original_id,
            original_rid=original_rid,
        )
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

    def create_document(
        self,
        prefix: str,
        title: str,
        *,
        digits: int = 3,
        parent: str | None = None,
    ) -> Document:
        """Create a new document and persist it to disk."""

        prefix = prefix.strip()
        if not prefix:
            raise ValueError("prefix cannot be empty")
        if not self._PREFIX_RE.match(prefix):
            raise ValueError("prefix must start with a capital letter and contain only A-Z, 0-9 or underscore")
        if digits <= 0:
            raise ValueError("digits must be positive")
        if prefix in self.documents:
            raise ValueError(f"document already exists: {prefix}")
        if parent:
            parent = parent.strip()
            if parent == prefix:
                raise ValueError("document cannot be its own parent")
            if parent not in self.documents:
                raise ValueError(f"unknown parent document: {parent}")
        doc = Document(
            prefix=prefix,
            title=title or prefix,
            digits=digits,
            parent=parent or None,
        )
        save_document(self.root / prefix, doc)
        self.load_documents()
        return self.documents[prefix]

    def rename_document(
        self,
        prefix: str,
        *,
        title: str | None = None,
        digits: int | None = None,
    ) -> Document:
        """Update metadata of document ``prefix``."""

        doc = self.documents.get(prefix)
        if doc is None:
            raise ValueError(f"unknown document prefix: {prefix}")
        updated = False
        if title is not None:
            doc.title = title
            updated = True
        if digits is not None:
            if digits <= 0:
                raise ValueError("digits must be positive")
            doc.digits = digits
            updated = True
        if not updated:
            return doc
        save_document(self.root / prefix, doc)
        self.load_documents()
        return self.documents[prefix]

    # ------------------------------------------------------------------
    def iter_links(self) -> Iterable[Tuple[str, str]]:
        """Yield ``(child_rid, parent_rid)`` pairs for requirements."""

        return doc_iter_links(self.root)
