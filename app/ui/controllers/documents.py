from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from collections.abc import Iterable

from ...services.requirements import (
    RequirementsService,
    Document,
    DocumentNotFoundError,
    LabelDef,
    RequirementIDCollisionError,
    RequirementNotFoundError,
    ValidationError,
    iter_links,
    parse_rid,
    rid_for,
)
from ...core.model import Requirement, requirement_from_dict, requirement_to_dict
from ...core.trace_matrix import TraceMatrix, TraceMatrixConfig, build_trace_matrix


@dataclass
class DocumentsController:
    """Load documents and their items for the GUI."""

    service: RequirementsService
    model: object

    def __post_init__(self) -> None:
        self.documents: dict[str, Document] = {}

    _PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

    # ------------------------------------------------------------------
    def load_documents(self) -> dict[str, Document]:
        """Populate ``documents`` from the service and return them."""

        self.documents = self.service.load_documents(refresh=True)
        return self.documents

    def load_items(self, prefix: str) -> dict[str, list[int]]:
        """Load items for document ``prefix`` into the model.

        Returns a mapping of parent requirement RID to list of linked item ids.
        """
        try:
            doc = self._get_document(prefix)
        except ValueError:
            self.model.set_requirements([])
            return {}
        items: list[Requirement] = []
        derived_map: dict[str, list[int]] = {}
        for item_id in self.service.list_item_ids(prefix):
            data, _mtime = self.service.load_item(prefix, item_id)
            rid = rid_for(doc, item_id)
            req = requirement_from_dict(data, doc_prefix=doc.prefix, rid=rid)
            items.append(req)
            for parent in getattr(req, "links", []):
                parent_rid = getattr(parent, "rid", parent)
                derived_map.setdefault(parent_rid, []).append(req.id)
        self.model.set_requirements(items)
        return derived_map

    def collect_labels(self, prefix: str) -> tuple[list[LabelDef], bool]:
        """Return labels and free-form flag for document ``prefix``."""

        return self.service.collect_label_defs(prefix)

    def build_trace_matrix(self, config: TraceMatrixConfig) -> TraceMatrix:
        """Construct traceability matrix for ``config`` using cached documents."""

        if not self.documents:
            self.load_documents()
        return build_trace_matrix(self.service.root, config, docs=self.documents)

    # helpers ---------------------------------------------------------
    def _get_document(self, prefix: str) -> Document:
        doc = self.documents.get(prefix)
        if doc is not None:
            return doc
        try:
            doc = self.service.get_document(prefix)
        except DocumentNotFoundError as exc:
            raise ValueError(f"unknown document prefix: {prefix}") from exc
        self.documents[prefix] = doc
        return doc

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
        existing_ids = set(self.service.list_item_ids(prefix))
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

        doc = self._get_document(prefix)
        return self.service.next_item_id(prefix)

    def add_requirement(self, prefix: str, req: Requirement) -> None:
        """Add ``req`` to the in-memory model for document ``prefix``."""

        doc = self._get_document(prefix)
        self._ensure_unique_id(prefix, doc, req)
        req.doc_prefix = prefix
        req.rid = rid_for(doc, req.id)
        self.model.add(req)

    def save_requirement(self, prefix: str, req: Requirement) -> Path:
        """Persist ``req`` within document ``prefix`` and return file path."""

        doc = self._get_document(prefix)
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
        return self.service.save_requirement_payload(prefix, data)

    def delete_requirement(self, prefix: str, req_id: int) -> str:
        """Remove requirement ``req_id`` from document ``prefix``."""

        try:
            doc = self._get_document(prefix)
        except ValueError as exc:
            rid = f"{prefix}{req_id}"
            raise RequirementNotFoundError(rid) from exc
        rid = rid_for(doc, req_id)
        try:
            canonical = self.service.delete_requirement(rid)
        except ValidationError as exc:
            raise ValidationError(f"{rid}: {exc}") from exc
        self.model.delete(req_id)
        return canonical

    def delete_document(self, prefix: str) -> bool:
        """Remove document ``prefix`` and its descendants."""

        removed = self.service.delete_document(prefix)
        if removed:
            self.load_documents()
            self.model.set_requirements([])
        return removed

    def create_document(
        self,
        prefix: str,
        title: str,
        *,
        parent: str | None = None,
    ) -> Document:
        """Create a new document and persist it to disk."""

        prefix = prefix.strip()
        if not prefix:
            raise ValueError("prefix cannot be empty")
        if not self._PREFIX_RE.match(prefix):
            raise ValueError("prefix must start with a capital letter and contain only A-Z, 0-9 or underscore")
        if prefix in self.documents:
            raise ValueError(f"document already exists: {prefix}")
        if parent:
            parent = parent.strip()
            if parent == prefix:
                raise ValueError("document cannot be its own parent")
            if parent not in self.documents:
                raise ValueError(f"unknown parent document: {parent}")
        doc = self.service.create_document(
            prefix=prefix,
            title=title or prefix,
            parent=parent or None,
        )
        self.load_documents()
        return self.documents[prefix]

    def rename_document(
        self,
        prefix: str,
        *,
        title: str | None = None,
    ) -> Document:
        """Update metadata of document ``prefix``."""

        doc = self.documents.get(prefix)
        if doc is None:
            try:
                doc = self.service.get_document(prefix)
            except DocumentNotFoundError as exc:
                raise ValueError(f"unknown document prefix: {prefix}") from exc
            self.documents[prefix] = doc
        updated = False
        if title is not None:
            doc.title = title
            updated = True
        if not updated:
            return doc
        self.service.save_document(doc)
        self.load_documents()
        return self.documents[prefix]

    # ------------------------------------------------------------------
    def iter_links(self) -> Iterable[tuple[str, str]]:
        """Yield ``(child_rid, parent_rid)`` pairs for requirements."""

        return iter_links(self.service.root)

    @property
    def root(self) -> Path:
        """Return the filesystem root backing the requirements service."""

        return self.service.root
