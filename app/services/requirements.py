"""High-level wrappers around the document store for requirements management."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
__all__ = [
    "Document",
    "DocumentLabels",
    "DocumentNotFoundError",
    "LabelDef",
    "RequirementIDCollisionError",
    "RequirementNotFoundError",
    "RequirementPage",
    "ValidationError",
    "RequirementsService",
    "iter_links",
    "label_color",
    "stable_color",
    "parse_rid",
    "rid_for",
]

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
        """Normalise the configured root into a :class:`~pathlib.Path`."""
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
        docs = self._ensure_documents()
        return doc_store.save_item(directory, doc, payload, docs=docs)

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

    def copy_requirement(
        self,
        rid: str,
        *,
        new_prefix: str,
        overrides: Mapping[str, Any] | None = None,
        reset_revision: bool = True,
    ) -> Requirement:
        """Duplicate requirement ``rid`` under ``new_prefix``."""

        docs = self._ensure_documents()
        original = doc_store.get_requirement(self.root, rid, docs=docs)
        payload = original.to_mapping()

        if reset_revision:
            payload["revision"] = 1
            payload["modified_at"] = ""
            payload["approved_at"] = None

        if overrides:
            payload.update(overrides)

        labels = payload.get("labels", [])
        if isinstance(labels, Sequence):
            promoted = self._promote_label_definitions(new_prefix, labels, docs)
            if promoted:
                docs = self._ensure_documents(refresh=True)

        return doc_store.create_requirement(
            self.root,
            prefix=new_prefix,
            data=payload,
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
        """Update a single field on the requirement identified by ``rid``."""
        docs = self._ensure_documents()
        return doc_store.update_requirement_field(
            self.root,
            rid,
            field=field,
            value=value,
            docs=docs,
        )

    def set_requirement_labels(self, rid: str, labels: Sequence[str]) -> Requirement:
        """Replace labels associated with ``rid`` ensuring validation."""
        docs = self._ensure_documents()
        try:
            prefix, _ = doc_store.parse_rid(rid)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        promoted = self._promote_label_definitions(prefix, labels, docs)
        requirement = doc_store.set_requirement_labels(
            self.root,
            rid,
            labels=labels,
            docs=docs,
        )
        if promoted:
            self._ensure_documents(refresh=True)
        return requirement

    def sync_labels_from_requirements(self, prefix: str) -> list[LabelDef]:
        """Promote missing labels observed on requirements for ``prefix``."""

        docs = self._ensure_documents()
        requirements = doc_store.load_requirements(
            self.root, prefixes=[prefix], docs=docs
        )
        observed: list[str] = []
        for requirement in requirements:
            observed.extend(requirement.labels)
        promoted = self._promote_label_definitions(prefix, observed, docs)
        if promoted:
            self._ensure_documents(refresh=True)
        return promoted

    def set_requirement_attachments(
        self,
        rid: str,
        attachments: Sequence[Mapping[str, Any]],
    ) -> Requirement:
        """Synchronise attachment metadata for requirement ``rid``."""
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
        """Persist traceability links for requirement ``rid``."""
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
        """Create a directional link between ``source_rid`` and ``derived_rid``."""
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

    def describe_label_definitions(self, prefix: str) -> dict[str, object]:
        """Return detailed metadata about labels available to ``prefix``."""

        docs = self._ensure_documents()
        document = docs.get(prefix)
        if document is None:
            raise DocumentNotFoundError(prefix)

        chain: list[Document] = []
        current: Document | None = document
        effective_freeform = False
        while current is not None:
            chain.append(current)
            effective_freeform = effective_freeform or current.labels.allow_freeform
            parent_prefix = current.parent
            if not parent_prefix:
                break
            current = docs.get(parent_prefix)
            if current is None:
                # Reload documents to handle out-of-date caches gracefully.
                current = doc_store.load_document(self.root / parent_prefix)
                docs[parent_prefix] = current

        entries: list[dict[str, object]] = []
        for source in reversed(chain):
            for definition in source.labels.defs:
                entries.append(
                    {
                        "key": definition.key,
                        "title": definition.title,
                        "color": doc_store.label_color(definition),
                        "defined_in": source.prefix,
                        "editable": source.prefix == prefix,
                    }
                )

        return {
            "prefix": prefix,
            "document_allow_freeform": document.labels.allow_freeform,
            "effective_allow_freeform": effective_freeform,
            "labels": entries,
        }

    # ------------------------------------------------------------------
    def _promote_label_definitions(
        self,
        prefix: str,
        labels: Sequence[str],
        docs: Mapping[str, Document],
    ) -> list[LabelDef]:
        """Ensure that labels applied to ``prefix`` are defined in metadata."""

        defs, allow_freeform = doc_store.collect_label_defs(prefix, docs)
        if not allow_freeform:
            return []

        known = {definition.key for definition in defs}
        new_keys: list[str] = []
        seen: set[str] = set()
        for label in labels:
            if not isinstance(label, str):
                continue
            if label in seen:
                continue
            seen.add(label)
            if label not in known:
                new_keys.append(label)
        if not new_keys:
            return []

        chain: list[Document] = []
        current = docs.get(prefix)
        while current is not None:
            chain.append(current)
            if not current.parent:
                break
            current = docs.get(current.parent)

        target = next((doc for doc in chain if doc.labels.allow_freeform), None)
        if target is None:
            return []

        created: list[LabelDef] = []
        for key in new_keys:
            definition = LabelDef(
                key=key,
                title=self._format_label_title(key),
                color=doc_store.stable_color(key),
            )
            target.labels.defs.append(definition)
            created.append(definition)

        doc_store.save_document(self.root / target.prefix, target)
        return created

    @staticmethod
    def _format_label_title(key: str) -> str:
        """Return a human-friendly title derived from ``key``."""

        key = key.strip()
        if not key:
            return key
        parts = [segment for segment in re.split(r"[_\-\s]+", key) if segment]
        if not parts:
            return key
        transformed: list[str] = []
        for segment in parts:
            if segment.isupper():
                transformed.append(segment)
            else:
                transformed.append(segment.capitalize())
        return " ".join(transformed)

    def validate_labels(self, prefix: str, labels: Sequence[str]) -> str | None:
        """Validate ``labels`` for ``prefix`` returning an error message if any."""
        docs = self._ensure_documents()
        return doc_store.validate_labels(prefix, list(labels), docs)

    def is_ancestor(self, child_prefix: str, ancestor_prefix: str) -> bool:
        """Return ``True`` when ``ancestor_prefix`` is in the lineage of ``child_prefix``."""
        docs = self._ensure_documents()
        return doc_store.is_ancestor(child_prefix, ancestor_prefix, docs)

    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_label_definition(label: LabelDef) -> LabelDef:
        """Return sanitized clone of ``label`` ensuring defaults are applied."""

        key = label.key.strip()
        if not key:
            raise ValidationError("label key cannot be empty")
        title = label.title.strip() or key
        color = label.color.strip() if isinstance(label.color, str) else None
        if color == "":
            color = None
        return LabelDef(key=key, title=title, color=color)

    def _descendant_prefixes(self, prefix: str, docs: Mapping[str, Document]) -> list[str]:
        """Return prefixes where ``prefix`` is an ancestor (including itself)."""

        affected: list[str] = []
        for candidate in docs:
            if doc_store.is_ancestor(candidate, prefix, docs):
                affected.append(candidate)
        return affected

    def _propagate_label_definition_renames(
        self,
        prefix: str,
        renames: Mapping[str, str],
        docs: Mapping[str, Document],
    ) -> bool:
        """Rename inherited label definitions across descendant documents."""

        if not renames:
            return False

        changed_any = False
        for candidate in self._descendant_prefixes(prefix, docs):
            if candidate == prefix:
                continue

            document = docs.get(candidate)
            if document is None:
                continue

            updated: dict[str, LabelDef] = {}
            order: list[str] = []
            changed_document = False
            for definition in document.labels.defs:
                replacement = renames.get(definition.key)
                if replacement is not None:
                    changed_document = True
                    key = replacement
                else:
                    key = definition.key

                clone = LabelDef(key, definition.title, definition.color)
                if key not in updated:
                    order.append(key)
                updated[key] = clone

            if not changed_document:
                continue

            document.labels.defs = [updated[key] for key in order]
            doc_store.save_document(self.root / document.prefix, document)
            changed_any = True

        return changed_any

    def update_document_labels(
        self,
        prefix: str,
        *,
        original: Sequence[LabelDef],
        updated: Sequence[LabelDef],
        rename_choices: Mapping[str, tuple[str, bool]] | None = None,
        removal_choices: Mapping[str, bool] | None = None,
    ) -> list[LabelDef]:
        """Persist label definitions for ``prefix`` and apply side effects.

        ``rename_choices`` maps original keys to ``(new_key, propagate)`` pairs
        indicating whether requirement payloads should be updated.  ``removal_choices``
        records whether deleted labels should be stripped from existing
        requirements.
        """

        rename_choices = dict(rename_choices or {})
        removal_choices = dict(removal_choices or {})

        normalized: list[LabelDef] = []
        seen: set[str] = set()
        for definition in updated:
            sanitized = self._normalise_label_definition(definition)
            if sanitized.key in seen:
                raise ValidationError(f"duplicate label key: {sanitized.key}")
            seen.add(sanitized.key)
            normalized.append(sanitized)

        document = self.get_document(prefix)
        document.labels.defs = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in normalized]
        self.save_document(document)

        propagate_renames: dict[str, str] = {}
        for old_key, (new_key_raw, propagate) in rename_choices.items():
            if not propagate:
                continue
            if new_key_raw is None:
                continue
            new_key = new_key_raw.strip()
            if not new_key or new_key == old_key:
                continue
            propagate_renames[old_key] = new_key

        docs = self._ensure_documents()
        if self._propagate_label_definition_renames(prefix, propagate_renames, docs):
            docs = self._ensure_documents(refresh=True)

        updated_keys = {lbl.key for lbl in normalized}
        original_keys = {lbl.key for lbl in original}

        rename_map: dict[str, str] = {}
        for old_key, new_key in propagate_renames.items():
            if old_key not in original_keys:
                continue
            rename_map[old_key] = new_key

        removed_keys = {key for key in original_keys if key not in updated_keys}
        removal_targets = {
            key
            for key in removed_keys
            if removal_choices.get(key, False)
        }

        if not rename_map and not removal_targets:
            return normalized

        affected_prefixes = self._descendant_prefixes(prefix, docs)
        for candidate in affected_prefixes:
            requirements = doc_store.load_requirements(
                self.root, prefixes=[candidate], docs=docs
            )
            for requirement in requirements:
                if not requirement.labels:
                    continue
                changed = False
                new_labels: list[str] = []
                for label in requirement.labels:
                    replacement = rename_map.get(label)
                    if replacement is not None:
                        new_labels.append(replacement)
                        if replacement != label:
                            changed = True
                        continue
                    if label in removal_targets:
                        changed = True
                        continue
                    new_labels.append(label)
                if changed:
                    doc_store.set_requirement_labels(
                        self.root,
                        requirement.rid,
                        labels=new_labels,
                        docs=docs,
                    )

        return normalized

    def add_label_definition(
        self,
        prefix: str,
        *,
        key: str,
        title: str | None = None,
        color: str | None = None,
    ) -> LabelDef:
        """Append a new label definition to ``prefix`` document."""

        document = self.get_document(prefix)
        original = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in document.labels.defs]
        new_label = LabelDef(key=key, title=title or key, color=color)
        updated = [*original, new_label]
        normalized = self.update_document_labels(
            prefix,
            original=original,
            updated=updated,
            rename_choices={},
            removal_choices={},
        )
        return next(defn for defn in normalized if defn.key == new_label.key)

    def update_label_definition(
        self,
        prefix: str,
        *,
        key: str,
        new_key: str | None = None,
        title: str | None = None,
        color: str | None = None,
        propagate: bool = False,
    ) -> LabelDef:
        """Update ``key`` label definition for ``prefix`` document."""

        document = self.get_document(prefix)
        original = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in document.labels.defs]
        updated: list[LabelDef] = []
        target: LabelDef | None = None
        for definition in document.labels.defs:
            if definition.key == key:
                target = LabelDef(
                    key=new_key if new_key is not None else definition.key,
                    title=title if title is not None else definition.title,
                    color=color if color is not None else definition.color,
                )
                updated.append(target)
            else:
                updated.append(LabelDef(definition.key, definition.title, definition.color))

        if target is None:
            raise ValidationError(f"label {key} does not exist")

        rename_choices: dict[str, tuple[str, bool]] = {}
        if new_key is not None and new_key.strip() and new_key.strip() != key:
            rename_choices[key] = (new_key, propagate)

        normalized = self.update_document_labels(
            prefix,
            original=original,
            updated=updated,
            rename_choices=rename_choices,
            removal_choices={},
        )
        return next(defn for defn in normalized if defn.key == (new_key or key))

    def remove_label_definition(
        self,
        prefix: str,
        key: str,
        *,
        remove_from_requirements: bool = False,
    ) -> None:
        """Remove label ``key`` from ``prefix`` metadata."""

        document = self.get_document(prefix)
        original = [LabelDef(lbl.key, lbl.title, lbl.color) for lbl in document.labels.defs]
        updated = [
            LabelDef(definition.key, definition.title, definition.color)
            for definition in document.labels.defs
            if definition.key != key
        ]
        if len(updated) == len(original):
            raise ValidationError(f"label {key} does not exist")

        self.update_document_labels(
            prefix,
            original=original,
            updated=updated,
            rename_choices={},
            removal_choices={key: remove_from_requirements},
        )

    def list_requirements(
        self,
        *,
        page: int = 1,
        per_page: int = 50,
        status: str | None = None,
        labels: Sequence[str] | None = None,
    ) -> RequirementPage:
        """Return a paginated view across requirements filtered by metadata."""
        docs = self._ensure_documents()
        return doc_store.list_requirements(
            self.root,
            page=page,
            per_page=per_page,
            status=status,
            labels=labels,
            docs=docs,
        )

    def load_requirements(
        self, *, prefixes: Sequence[str] | None = None
    ) -> list[Requirement]:
        """Return requirements for ``prefixes`` refreshing link metadata."""
        docs = self._ensure_documents()
        return doc_store.load_requirements(
            self.root,
            prefixes=prefixes,
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
        """Search requirements by text and metadata returning a paginated result."""
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
