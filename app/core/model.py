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
    version: str = ""
    modified_at: str = ""
    labels: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    revision: int = 1
    approved_at: str | None = None
    notes: str = ""
    links: list[str] = field(default_factory=list)
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
    attachments_data = data.get("attachments") or []
    attachments = [Attachment(**a) for a in attachments_data]
    raw_links = data.get("links", [])
    links = [str(link) for link in raw_links] if isinstance(raw_links, list) else []
    statement = data.get("statement", data.get("text", ""))
    return Requirement(
        id=data["id"],
        title=data.get("title", ""),
        statement=statement,
        type=RequirementType(data.get("type")),
        status=Status(data.get("status")),
        owner=data.get("owner", ""),
        priority=Priority(data.get("priority")),
        source=data.get("source", ""),
        verification=Verification(data.get("verification")),
        acceptance=data.get("acceptance"),
        conditions=data.get("conditions", ""),
        version=data.get("version", ""),
        modified_at=normalize_timestamp(data.get("modified_at")),
        labels=list(data.get("labels") or []),
        attachments=attachments,
        revision=data.get("revision", 1),
        approved_at=(
            normalize_timestamp(data.get("approved_at"))
            if data.get("approved_at")
            else None
        ),
        notes=data.get("notes", ""),
        links=links,
        doc_prefix=doc_prefix,
        rid=rid,
    )


def requirement_to_dict(req: Requirement) -> dict[str, Any]:
    """Convert ``req`` into a plain ``dict`` suitable for JSON storage."""
    data = asdict(req)
    # ``doc_prefix`` and ``rid`` are derived from file location; omit
    data.pop("doc_prefix", None)
    data.pop("rid", None)
    if not data.get("links"):
        data.pop("links", None)
    for key in ("type", "status", "priority", "verification"):
        value = data.get(key)
        if isinstance(value, Enum):
            data[key] = value.value
    return data
