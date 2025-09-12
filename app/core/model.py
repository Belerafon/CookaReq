"""Domain models for requirements."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional, Any


class RequirementType(str, Enum):
    REQUIREMENT = "requirement"
    CONSTRAINT = "constraint"
    INTERFACE = "interface"


class Status(str, Enum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    BASELINED = "baselined"
    RETIRED = "retired"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Verification(str, Enum):
    INSPECTION = "inspection"
    ANALYSIS = "analysis"
    DEMONSTRATION = "demonstration"
    TEST = "test"


@dataclass
class Units:
    quantity: str
    nominal: float
    tolerance: Optional[float] = None


@dataclass
class Attachment:
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
    assumptions: List[str]
    method: str
    margin: str


@dataclass
class Links:
    """Grouping for miscellaneous requirement links."""

    verifies: List[RequirementLink] = field(default_factory=list)
    relates: List[RequirementLink] = field(default_factory=list)


@dataclass
class Requirement:
    id: int
    title: str
    statement: str
    type: RequirementType
    status: Status
    owner: str
    priority: Priority
    source: str
    verification: Verification
    acceptance: Optional[str] = None
    conditions: str = ""
    trace_up: str = ""
    trace_down: str = ""
    version: str = ""
    modified_at: str = ""
    units: Optional[Units] = None
    labels: List[str] = field(default_factory=list)
    attachments: List[Attachment] = field(default_factory=list)
    revision: int = 1
    approved_at: Optional[str] = None
    notes: str = ""
    parent: RequirementLink | None = None
    derived_from: List[RequirementLink] = field(default_factory=list)
    links: Links = field(default_factory=Links)
    derivation: Optional[DerivationInfo] = None


def requirement_from_dict(data: dict[str, Any]) -> Requirement:
    """Create :class:`Requirement` instance from a plain ``dict``.

    Nested ``attachments``, ``units`` and derivation structures are converted
    into their respective dataclasses. Missing optional fields fall back to
    sensible defaults.
    """
    units_data = data.get("units")
    units = Units(**units_data) if units_data else None
    attachments = [Attachment(**a) for a in data.get("attachments", [])]
    parent_data = data.get("parent")
    parent = RequirementLink(**parent_data) if parent_data else None
    derived_from = [RequirementLink(**d) for d in data.get("derived_from", [])]
    links_data = data.get("links", {})
    links = Links(
        verifies=[RequirementLink(**l) for l in links_data.get("verifies", [])],
        relates=[RequirementLink(**l) for l in links_data.get("relates", [])],
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
        modified_at=data.get("modified_at", ""),
        units=units,
        labels=list(data.get("labels", [])),
        attachments=attachments,
        revision=data.get("revision", 1),
        approved_at=data.get("approved_at"),
        notes=data.get("notes", ""),
        parent=parent,
        derived_from=derived_from,
        links=links,
        derivation=derivation,
    )


def requirement_to_dict(req: Requirement) -> dict[str, Any]:
    """Convert ``req`` into a plain ``dict`` suitable for JSON storage."""
    data = asdict(req)
    if "links" in data and not data["links"]["verifies"] and not data["links"]["relates"]:
        del data["links"]
    for key in ("type", "status", "priority", "verification"):
        value = data.get(key)
        if isinstance(value, Enum):
            data[key] = value.value
    data = {k: v for k, v in data.items() if v is not None}
    return data

