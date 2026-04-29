"""Common document store data structures and error types."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any
from collections.abc import Mapping, Sequence

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
    group_level: int = 0

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
        group_level_raw = data.get("groupLevel", 0)
        try:
            group_level = int(group_level_raw)
        except (TypeError, ValueError):
            group_level = 0
        if group_level not in (0, 1, 2, 3):
            group_level = 0
        return cls(key=str(key), title=str(title), color=color, group_level=group_level)

    def to_mapping(self) -> dict[str, Any]:
        """Serialise the label definition into a JSON-friendly mapping."""
        payload = asdict(self)
        payload["groupLevel"] = payload.pop("group_level", 0)
        return payload


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


@dataclass(slots=True)
class SharedArtifact:
    """Document-level artifact shared across all requirements."""

    id: str
    path: str
    title: str = ""
    note: str = ""
    include_in_export: bool = True
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> SharedArtifact:
        """Build a shared artifact entry from JSON mapping."""
        if not isinstance(data, Mapping):
            raise ValidationError("shared_artifact must be a mapping")
        artifact_id = str(data.get("id", "")).strip()
        if not artifact_id:
            raise ValidationError("shared_artifact.id is required")
        path = str(data.get("path", "")).strip()
        if not path:
            raise ValidationError("shared_artifact.path is required")
        title = str(data.get("title", "")).strip()
        note = str(data.get("note", ""))
        include_in_export = bool(data.get("include_in_export", True))
        raw_tags = data.get("tags", [])
        if raw_tags in (None, ""):
            tags = []
        elif isinstance(raw_tags, list):
            tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
        else:
            raise ValidationError("shared_artifact.tags must be a list")
        return cls(
            id=artifact_id,
            path=path,
            title=title,
            note=note,
            include_in_export=include_in_export,
            tags=tags,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Serialise shared artifact for JSON storage."""
        return {
            "id": self.id,
            "path": self.path,
            "title": self.title,
            "note": self.note,
            "include_in_export": self.include_in_export,
            "tags": list(self.tags),
        }


@dataclass(slots=True, init=False)
class Document:
    """Configuration describing a document in the hierarchy."""

    prefix: str
    title: str
    parent: str | None = None
    labels: DocumentLabels = field(default_factory=DocumentLabels)
    shared_artifacts: list[SharedArtifact] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        *,
        prefix: str,
        title: str,
        parent: str | None = None,
        labels: DocumentLabels | None = None,
        shared_artifacts: Sequence[SharedArtifact] | None = None,
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
        self.shared_artifacts = list(shared_artifacts or [])
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
        shared_artifacts_raw = data.get("shared_artifacts")
        if shared_artifacts_raw in (None, ""):
            shared_artifacts: list[SharedArtifact] = []
        elif isinstance(shared_artifacts_raw, list):
            shared_artifacts = [
                SharedArtifact.from_mapping(entry) for entry in shared_artifacts_raw
            ]
        else:
            raise ValidationError("shared_artifacts must be a list")
        seen_artifact_ids: set[str] = set()
        for artifact in shared_artifacts:
            if artifact.id in seen_artifact_ids:
                raise ValidationError("shared_artifact ids must be unique")
            seen_artifact_ids.add(artifact.id)
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
            shared_artifacts=shared_artifacts,
            attributes=attributes,
        )

    def to_mapping(self) -> dict[str, Any]:
        """Serialise the document configuration to JSON mapping."""
        return {
            "title": self.title,
            "parent": self.parent,
            "labels": self.labels.to_mapping(),
            "shared_artifacts": [
                artifact.to_mapping() for artifact in self.shared_artifacts
            ],
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
    "SharedArtifact",
    "Document",
    "RequirementPage",
]
