"""Document store public API and shared structures."""

from __future__ import annotations

import warnings

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Mapping

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from ..model import Requirement


class ValidationError(Exception):
    """Raised when requirement links or payload violate business rules."""


class RequirementError(Exception):
    """Base class for requirement storage exceptions."""


class DocumentNotFoundError(RequirementError):
    """Raised when a document prefix is unknown."""

    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        super().__init__(f"unknown document prefix: {prefix}")


class RequirementNotFoundError(RequirementError):
    """Raised when a requirement identifier cannot be located."""

    def __init__(self, rid: str) -> None:
        self.rid = rid
        super().__init__(f"requirement {rid} not found")


class RevisionMismatchError(RequirementError):
    """Raised when the caller provides an outdated revision."""

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"revision mismatch: expected {expected}, have {actual}")


class RequirementIDCollisionError(RequirementError):
    """Raised when attempting to reuse an existing requirement identifier."""

    def __init__(self, doc_prefix: str, req_id: int, *, rid: str | None = None) -> None:
        self.doc_prefix = doc_prefix
        self.req_id = req_id
        self.rid = rid or f"{doc_prefix}{req_id}"
        super().__init__(f"requirement {self.rid} already exists")


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
    defs: List[LabelDef] = field(default_factory=list)


@dataclass(init=False)
class Document:
    """Configuration describing a document in the hierarchy."""

    prefix: str
    title: str
    parent: str | None = None
    labels: DocumentLabels = field(default_factory=DocumentLabels)
    attributes: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        *,
        prefix: str,
        title: str,
        parent: str | None = None,
        labels: DocumentLabels | None = None,
        attributes: Mapping[str, Any] | None = None,
        **legacy_kwargs: Any,
    ) -> None:
        """Create a document definition.

        Historically :class:`Document` accepted a ``digits`` parameter that
        controlled zero padding of generated identifiers.  The current storage
        format always serialises plain integers, so the parameter is ignored but
        still accepted for backwards compatibility with cached GUI state and
        older tests.
        """

        digits = legacy_kwargs.pop("digits", None)
        if digits not in (None, ""):
            warnings.warn(
                "Document(digits=...) is ignored; identifiers are always stored "
                "without leading zeros.",
                DeprecationWarning,
                stacklevel=2,
            )
        if legacy_kwargs:
            unexpected = ", ".join(sorted(legacy_kwargs))
            raise TypeError(f"unexpected keyword argument(s): {unexpected}")

        self.prefix = prefix
        self.title = title
        self.parent = parent
        self.labels = labels or DocumentLabels()
        self.attributes = dict(attributes or {})


@dataclass
class RequirementPage:
    """Represent a paginated slice of requirements."""

    items: list["Requirement"]
    total: int
    page: int
    per_page: int


from .documents import (  # noqa: E402
    collect_label_defs,
    collect_labels,
    is_ancestor,
    label_color,
    load_document,
    load_documents,
    save_document,
    stable_color,
    validate_labels,
)
from .items import (  # noqa: E402
    create_requirement,
    delete_requirement,
    get_requirement,
    item_path,
    locate_item_path,
    list_item_ids,
    list_requirements,
    load_item,
    move_requirement,
    next_item_id,
    parse_rid,
    patch_requirement,
    rid_for,
    save_item,
    search_requirements,
)
from .links import (  # noqa: E402
    delete_document,
    delete_item,
    iter_links,
    link_requirements,
    plan_delete_document,
    plan_delete_item,
)

__all__ = [
    "ValidationError",
    "RequirementError",
    "DocumentNotFoundError",
    "RequirementNotFoundError",
    "RevisionMismatchError",
    "RequirementIDCollisionError",
    "LabelDef",
    "DocumentLabels",
    "Document",
    "RequirementPage",
    "collect_label_defs",
    "collect_labels",
    "is_ancestor",
    "label_color",
    "load_document",
    "load_documents",
    "save_document",
    "stable_color",
    "validate_labels",
    "create_requirement",
    "delete_requirement",
    "get_requirement",
    "item_path",
    "locate_item_path",
    "list_item_ids",
    "list_requirements",
    "load_item",
    "move_requirement",
    "next_item_id",
    "parse_rid",
    "patch_requirement",
    "rid_for",
    "save_item",
    "search_requirements",
    "delete_document",
    "delete_item",
    "iter_links",
    "link_requirements",
    "plan_delete_document",
    "plan_delete_item",
]
