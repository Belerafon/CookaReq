"""Common document store data structures and error types."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any
from collections.abc import Mapping

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from ..model import Requirement


class ValidationError(Exception):
    """Raised when requirement links or payload violate business rules."""

class RequirementError(Exception):
    """Base class for requirement storage exceptions."""

class DocumentNotFoundError(RequirementError):
    """Raised when a document prefix is unknown."""

    def __init__(self, prefix: str) -> None:
        """Store missing document ``prefix`` for diagnostics."""
        self.prefix = prefix
        super().__init__(f"unknown document prefix: {prefix}")


class RequirementNotFoundError(RequirementError):
    """Raised when a requirement identifier cannot be located."""

    def __init__(self, rid: str) -> None:
        """Record missing requirement identifier ``rid``."""
        self.rid = rid
        super().__init__(f"requirement {rid} not found")


class RequirementIDCollisionError(RequirementError):
    """Raised when attempting to reuse an existing requirement identifier."""

    def __init__(self, doc_prefix: str, req_id: int, *, rid: str | None = None) -> None:
        """Capture conflicting identifier metadata for later reporting."""
        self.doc_prefix = doc_prefix
        self.req_id = req_id
        self.rid = rid or f"{doc_prefix}{req_id}"
        super().__init__(f"requirement {self.rid} already exists")


@dataclass(slots=True)
class LabelDef:
    """Definition of a label available to document items."""

    key: str
    title: str
    color: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> LabelDef:
        """Build a label definition from a JSON mapping."""
        if not isinstance(data, Mapping):
            raise ValidationError("label definition must be a mapping")
        try:
            key = data["key"]
            title = data["title"]
        except KeyError as exc:  # pragma: no cover - defensive
            raise ValidationError(f"label definition missing {exc.args[0]}") from exc
        color_raw = data.get("color")
        color = None if color_raw in (None, "") else str(color_raw)
        return cls(key=str(key), title=str(title), color=color)

    def to_mapping(self) -> dict[str, Any]:
        """Serialise the label definition into a JSON-friendly mapping."""
        return asdict(self)


@dataclass(slots=True)
class DocumentLabels:
    """Label configuration for a document."""

    allow_freeform: bool = False
    defs: list[LabelDef] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> DocumentLabels:
        """Construct labels configuration from JSON mapping."""
        if not isinstance(data, Mapping):
            raise ValidationError("labels must be a mapping")
        allow_raw = data.get("allowFreeform", False)
        allow_freeform = bool(allow_raw)
        raw_defs = data.get("defs", [])
        if raw_defs in (None, ""):
            raw_defs = []
        if not isinstance(raw_defs, list):
            raise ValidationError("labels.defs must be a list")
        defs: list[LabelDef] = []
        for index, entry in enumerate(raw_defs):
            if not isinstance(entry, Mapping):
                raise ValidationError(f"labels.defs[{index}] must be a mapping")
            defs.append(LabelDef.from_mapping(entry))
        return cls(allow_freeform=allow_freeform, defs=defs)

    def to_mapping(self) -> dict[str, Any]:
        """Serialise labels configuration to JSON mapping."""
        return {
            "allowFreeform": self.allow_freeform,
            "defs": [label.to_mapping() for label in self.defs],
        }


@dataclass(slots=True, init=False)
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
        **extra: Any,
    ) -> None:
        """Create a document definition."""
        if extra:
            unexpected = ", ".join(sorted(extra))
            raise TypeError(f"unexpected keyword argument(s): {unexpected}")

        self.prefix = prefix
        self.title = title
        self.parent = parent
        self.labels = labels or DocumentLabels()
        self.attributes = dict(attributes or {})

    @classmethod
    def from_mapping(cls, *, prefix: str, data: Mapping[str, Any]) -> Document:
        """Construct a :class:`Document` from raw JSON data."""
        if not isinstance(data, Mapping):
            raise ValidationError("document metadata must be a mapping")
        stored_prefix = data.get("prefix")
        if stored_prefix is not None and stored_prefix != prefix:
            raise ValidationError(
                f"document prefix mismatch: directory '{prefix}' != stored '{stored_prefix}'"
            )
        title_raw = data.get("title", prefix)
        title = prefix if title_raw is None else str(title_raw)
        parent_raw = data.get("parent")
        if parent_raw in (None, ""):
            parent = None
        elif isinstance(parent_raw, str):
            parent = parent_raw
        else:
            raise ValidationError("parent must be a string or null")
        labels_raw = data.get("labels")
        if labels_raw is None:
            labels = DocumentLabels()
        elif isinstance(labels_raw, Mapping):
            labels = DocumentLabels.from_mapping(labels_raw)
        else:
            raise ValidationError("labels must be a mapping")
        attributes_raw = data.get("attributes", {})
        if attributes_raw in (None, ""):
            attributes = {}
        elif isinstance(attributes_raw, Mapping):
            attributes = dict(attributes_raw)
        else:
            raise ValidationError("attributes must be a mapping")
        return cls(
            prefix=prefix,
            title=title,
            parent=parent,
            labels=labels,
            attributes=attributes,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Serialise the document configuration to JSON mapping."""
        return {
            "title": self.title,
            "parent": self.parent,
            "labels": self.labels.to_mapping(),
            "attributes": dict(self.attributes),
        }


@dataclass(slots=True)
class RequirementPage:
    """Represent a paginated slice of requirements."""

    items: list[Requirement]
    total: int
    page: int
    per_page: int


__all__ = [
    "ValidationError",
    "RequirementError",
    "DocumentNotFoundError",
    "RequirementNotFoundError",
    "RequirementIDCollisionError",
    "LabelDef",
    "DocumentLabels",
    "Document",
    "RequirementPage",
]
