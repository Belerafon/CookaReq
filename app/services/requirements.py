from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..core import document_store as doc_store
from ..core.document_store import (
    Document,
    DocumentLabels,
    DocumentNotFoundError,
    LabelDef,
    RequirementIDCollisionError,
    RequirementNotFoundError,
    RequirementPage,
    ValidationError,
)
from ..core.model import Requirement

# Re-export selected helpers so callers do not need to depend on ``document_store``.
iter_links = doc_store.iter_links
label_color = doc_store.label_color
stable_color = doc_store.stable_color
parse_rid = doc_store.parse_rid
rid_for = doc_store.rid_for


@dataclass
class RequirementsService:
    """High level gateway around the document store."""

    root: Path | str
    _documents: dict[str, Document] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    # ------------------------------------------------------------------
    def clear_cache(self) -> None:
        """Drop cached document metadata."""

        self._documents = None

    # ------------------------------------------------------------------
    def _ensure_documents(self, *, refresh: bool = False) -> dict[str, Document]:
        if refresh or self._documents is None:
            self._documents = doc_store.load_documents(self.root)
        return self._documents

    def load_documents(self, *, refresh: bool = False) -> dict[str, Document]:
        """Return mapping of prefix to :class:`Document` under ``root``."""

        docs = self._ensure_documents(refresh=refresh)
        return dict(docs)

    def get_document(self, prefix: str) -> Document:
        """Return document ``prefix`` loading it from disk when necessary."""

        docs = self._ensure_documents()
        doc = docs.get(prefix)
        if doc is not None:
            return doc
        try:
            doc = doc_store.load_document(self.root / prefix)
        except FileNotFoundError as exc:
            raise DocumentNotFoundError(prefix) from exc
        # Reload the cache so future operations see the new document.
        docs = self._ensure_documents(refresh=True)
        cached = docs.get(prefix)
        if cached is None:
            raise DocumentNotFoundError(prefix)
        return cached

    # ------------------------------------------------------------------
    def save_document(self, document: Document) -> Path:
        """Persist ``document`` metadata and refresh the cache."""

        path = doc_store.save_document(self.root / document.prefix, document)
        self._ensure_documents(refresh=True)
        return path

    def create_document(
        self,
        *,
        prefix: str,
        title: str,
        parent: str | None = None,
        labels: DocumentLabels | None = None,
    ) -> Document:
        """Create and persist a new document."""

        document = Document(prefix=prefix, title=title, parent=parent, labels=labels)
        self.save_document(document)
        return document

    def delete_document(self, prefix: str) -> bool:
        """Delete document ``prefix`` and refresh the cache on success."""

        docs = self._ensure_documents()
        removed = doc_store.delete_document(self.root, prefix, docs)
        if removed:
            self._ensure_documents(refresh=True)
        return removed

    def plan_delete_document(self, prefix: str) -> tuple[list[str], list[str]]:
        """Return prospective documents and items affected by deletion."""

        docs = self._ensure_documents()
        return doc_store.plan_delete_document(self.root, prefix, docs)

    # ------------------------------------------------------------------
    def list_item_ids(self, prefix: str) -> list[int]:
        """Return sorted item identifiers for document ``prefix``."""

        doc = self.get_document(prefix)
        directory = self.root / prefix
        return sorted(doc_store.list_item_ids(directory, doc))

    def load_item(self, prefix: str, item_id: int) -> tuple[dict[str, Any], float]:
        """Return raw payload and modification time for requirement ``item_id``."""

        doc = self.get_document(prefix)
        directory = self.root / prefix
        return doc_store.load_item(directory, doc, item_id)

    def next_item_id(self, prefix: str) -> int:
        """Return the next available numeric identifier for ``prefix``."""

        doc = self.get_document(prefix)
        directory = self.root / prefix
        return doc_store.next_item_id(directory, doc)

    def save_requirement_payload(self, prefix: str, payload: Mapping[str, Any]) -> Path:
        """Persist raw requirement ``payload`` under document ``prefix``."""

        doc = self.get_document(prefix)
        directory = self.root / prefix
        return doc_store.save_item(directory, doc, dict(payload))

    def delete_requirement(self, rid: str) -> str:
        """Delete requirement ``rid`` enforcing revision semantics."""

        docs = self._ensure_documents()
        return doc_store.delete_requirement(self.root, rid, docs=docs)

    def plan_delete_requirement(self, rid: str) -> tuple[bool, list[str]]:
        """Return existence flag and references for requirement ``rid``."""

        docs = self._ensure_documents()
        return doc_store.plan_delete_item(self.root, rid, docs)

    # ------------------------------------------------------------------
    def create_requirement(self, prefix: str, data: Mapping[str, Any]) -> Requirement:
        """Create a new requirement within ``prefix``."""

        docs = self._ensure_documents()
        return doc_store.create_requirement(
            self.root,
            prefix=prefix,
            data=data,
            docs=docs,
        )

    def get_requirement(self, rid: str) -> Requirement:
        """Return requirement ``rid`` using cached documents when possible."""

        docs = self._ensure_documents()
        return doc_store.get_requirement(self.root, rid, docs=docs)

    def move_requirement(
        self,
        rid: str,
        *,
        new_prefix: str,
        payload: Mapping[str, Any],
    ) -> Requirement:
        """Move requirement ``rid`` to document ``new_prefix``."""

        docs = self._ensure_documents()
        return doc_store.move_requirement(
            self.root,
            rid,
            new_prefix=new_prefix,
            payload=payload,
            docs=docs,
        )

    def update_requirement_field(
        self,
        rid: str,
        *,
        field: str,
        value: Any,
    ) -> Requirement:
        docs = self._ensure_documents()
        return doc_store.update_requirement_field(
            self.root,
            rid,
            field=field,
            value=value,
            docs=docs,
        )

    def set_requirement_labels(self, rid: str, labels: Sequence[str]) -> Requirement:
        docs = self._ensure_documents()
        return doc_store.set_requirement_labels(
            self.root,
            rid,
            labels=labels,
            docs=docs,
        )

    def set_requirement_attachments(
        self,
        rid: str,
        attachments: Sequence[Mapping[str, Any]],
    ) -> Requirement:
        docs = self._ensure_documents()
        return doc_store.set_requirement_attachments(
            self.root,
            rid,
            attachments=attachments,
            docs=docs,
        )

    def set_requirement_links(
        self,
        rid: str,
        links: Sequence[Mapping[str, Any] | str],
    ) -> Requirement:
        docs = self._ensure_documents()
        return doc_store.set_requirement_links(
            self.root,
            rid,
            links=links,
            docs=docs,
        )

    def link_requirements(
        self,
        *,
        source_rid: str,
        derived_rid: str,
        link_type: str,
    ) -> Requirement:
        docs = self._ensure_documents()
        return doc_store.link_requirements(
            self.root,
            source_rid=source_rid,
            derived_rid=derived_rid,
            link_type=link_type,
            docs=docs,
        )

    # ------------------------------------------------------------------
    def collect_label_defs(self, prefix: str) -> tuple[list[LabelDef], bool]:
        """Return label definitions and freeform flag for ``prefix``."""

        docs = self._ensure_documents()
        return doc_store.collect_label_defs(prefix, docs)

    def validate_labels(self, prefix: str, labels: Sequence[str]) -> str | None:
        docs = self._ensure_documents()
        return doc_store.validate_labels(prefix, list(labels), docs)

    def is_ancestor(self, child_prefix: str, ancestor_prefix: str) -> bool:
        docs = self._ensure_documents()
        return doc_store.is_ancestor(child_prefix, ancestor_prefix, docs)

    def list_requirements(
        self,
        *,
        page: int = 1,
        per_page: int = 50,
        status: str | None = None,
        labels: Sequence[str] | None = None,
    ) -> RequirementPage:
        docs = self._ensure_documents()
        return doc_store.list_requirements(
            self.root,
            page=page,
            per_page=per_page,
            status=status,
            labels=labels,
            docs=docs,
        )

    def search_requirements(
        self,
        *,
        query: str | None = None,
        labels: Sequence[str] | None = None,
        status: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> RequirementPage:
        docs = self._ensure_documents()
        return doc_store.search_requirements(
            self.root,
            query=query,
            labels=labels,
            status=status,
            page=page,
            per_page=per_page,
            docs=docs,
        )
