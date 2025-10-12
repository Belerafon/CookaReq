from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from collections.abc import Iterable, Mapping, Sequence

_UNSET = object()

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
from ...core.model import Requirement
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
            self._get_document(prefix)
        except ValueError:
            self.model.set_requirements([])
            return {}
        items = self.service.load_requirements(prefixes=[prefix])
        derived_map: dict[str, list[int]] = {}
        for req in items:
            for parent in getattr(req, "links", []):
                parent_rid = getattr(parent, "rid", parent)
                derived_map.setdefault(parent_rid, []).append(req.id)
        self.model.set_requirements(items)
        return derived_map

    def collect_labels(self, prefix: str) -> tuple[list[LabelDef], bool]:
        """Return labels and free-form flag for document ``prefix``."""
        return self.service.collect_label_defs(prefix)

    def sync_labels_from_requirements(self, prefix: str) -> list[LabelDef]:
        """Ensure that labels used by requirements are declared in metadata."""

        promoted = self.service.sync_labels_from_requirements(prefix)
        if promoted:
            self.load_documents()
        return promoted

    def update_document_labels(
        self,
        prefix: str,
        *,
        original: Sequence[LabelDef],
        updated: Sequence[LabelDef],
        rename_choices: Mapping[str, tuple[str, bool]],
        removal_choices: Mapping[str, bool],
    ) -> None:
        """Persist label changes for ``prefix`` and refresh caches."""

        self.service.update_document_labels(
            prefix,
            original=original,
            updated=updated,
            rename_choices=rename_choices,
            removal_choices=removal_choices,
        )
        self.load_documents()

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
        self._get_document(prefix)
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
        data = req.to_mapping()
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
        self.service.create_document(
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
        parent: str | None | object = _UNSET,
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
        if title is not None and title != doc.title:
            doc.title = title
            updated = True
        if parent is not _UNSET:
            new_parent = parent
            if isinstance(new_parent, str):
                new_parent = new_parent.strip() or None
            if new_parent == doc.prefix:
                raise ValueError("document cannot be its own parent")
            if new_parent:
                if new_parent not in self.documents:
                    self.load_documents()
                if new_parent not in self.documents:
                    raise ValueError(f"unknown parent document: {new_parent}")
                if self.service.is_ancestor(new_parent, doc.prefix):
                    raise ValueError("document cannot be moved under its own descendant")
            if doc.parent != new_parent:
                doc.parent = new_parent
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
