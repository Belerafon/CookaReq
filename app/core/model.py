"""Domain models for requirements."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from ..util.time import normalize_timestamp


class RequirementType(str, Enum):
    """Enumerate supported requirement categories."""

    REQUIREMENT = "requirement"
    CONSTRAINT = "constraint"
    INTERFACE = "interface"


class Status(str, Enum):
    """Enumerate requirement lifecycle states."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    BASELINED = "baselined"
    RETIRED = "retired"


class Priority(str, Enum):
    """Enumerate requirement priority levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Verification(str, Enum):
    """Enumerate possible verification methods."""

    INSPECTION = "inspection"
    ANALYSIS = "analysis"
    DEMONSTRATION = "demonstration"
    TEST = "test"


@dataclass
class Attachment:
    """Represent a file attached to a requirement."""

    path: str
    note: str = ""


@dataclass
class RequirementLink:
    """Reference to another requirement with revision tracking."""

    source_id: int
    source_revision: int
    suspect: bool = False


# Backwards compatible alias for existing code/tests
DerivationLink = RequirementLink


@dataclass
class DerivationInfo:
    """Details describing how the requirement was derived."""

    rationale: str
    assumptions: list[str]


@dataclass
class Links:
    """Grouping for miscellaneous requirement links."""

    verifies: list[RequirementLink] = field(default_factory=list)
    relates: list[RequirementLink] = field(default_factory=list)


@dataclass
class Requirement:
    """Represent a requirement with metadata and trace links."""

    id: int
    title: str
    statement: str
    type: RequirementType
    status: Status
    owner: str
    priority: Priority
    source: str
    verification: Verification
    acceptance: str | None = None
    conditions: str = ""
    trace_up: str = ""
    trace_down: str = ""
    version: str = ""
    modified_at: str = ""
    labels: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    revision: int = 1
    approved_at: str | None = None
    notes: str = ""
    parent: RequirementLink | None = None
    derived_from: list[RequirementLink] = field(default_factory=list)
    links: Links = field(default_factory=Links)
    derivation: DerivationInfo | None = None
    # document-related metadata
    doc_prefix: str = ""
    rid: str = ""


def requirement_from_dict(
    data: dict[str, Any], *, doc_prefix: str = "", rid: str = ""
) -> Requirement:
    """Create :class:`Requirement` instance from a plain ``dict``.

    Nested ``attachments`` and derivation structures are converted
    into their respective dataclasses. Missing optional fields fall back to
    sensible defaults.
    """
    attachments = [Attachment(**a) for a in data.get("attachments", [])]
    parent_data = data.get("parent")
    parent = RequirementLink(**parent_data) if parent_data else None
    derived_from = [RequirementLink(**d) for d in data.get("derived_from", [])]
    links_data = data.get("links", {})
    links = Links(
        verifies=[
            RequirementLink(**link_data) for link_data in links_data.get("verifies", [])
        ],
        relates=[
            RequirementLink(**link_data) for link_data in links_data.get("relates", [])
        ],
    )
    derivation_data = data.get("derivation")
    derivation = DerivationInfo(**derivation_data) if derivation_data else None
    return Requirement(
        id=data["id"],
        title=data.get("title", ""),
        statement=data.get("statement", ""),
        type=RequirementType(data.get("type")),
        status=Status(data.get("status")),
        owner=data.get("owner", ""),
        priority=Priority(data.get("priority")),
        source=data.get("source", ""),
        verification=Verification(data.get("verification")),
        acceptance=data.get("acceptance"),
        conditions=data.get("conditions", ""),
        trace_up=data.get("trace_up", ""),
        trace_down=data.get("trace_down", ""),
        version=data.get("version", ""),
        modified_at=normalize_timestamp(data.get("modified_at")),
        labels=list(data.get("labels", [])),
        attachments=attachments,
        revision=data.get("revision", 1),
        approved_at=(
            normalize_timestamp(data.get("approved_at"))
            if data.get("approved_at")
            else None
        ),
        notes=data.get("notes", ""),
        parent=parent,
        derived_from=derived_from,
        links=links,
        derivation=derivation,
        doc_prefix=doc_prefix,
        rid=rid,
    )


def requirement_to_dict(req: Requirement) -> dict[str, Any]:
    """Convert ``req`` into a plain ``dict`` suitable for JSON storage."""
    data = asdict(req)
    # ``doc_prefix`` and ``rid`` are derived from file location; omit
    data.pop("doc_prefix", None)
    data.pop("rid", None)
    if (
        "links" in data
        and not data["links"]["verifies"]
        and not data["links"]["relates"]
    ):
        del data["links"]
    for key in ("type", "status", "priority", "verification"):
        value = data.get(key)
        if isinstance(value, Enum):
            data[key] = value.value
    return {k: v for k, v in data.items() if v is not None}
