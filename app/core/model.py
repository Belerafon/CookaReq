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
    rationale: str = ""
    assumptions: str = ""
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
    required = [
        "id",
        "title",
        "statement",
        "type",
        "status",
        "owner",
        "priority",
        "source",
        "verification",
    ]
    for field in required:
        if field not in data:
            raise KeyError(f"missing required field: {field}")

    for field in ("text", "tags"):
        if field in data:
            raise KeyError(f"unsupported field: {field}")

    attachments_data = data.get("attachments", [])
    if not isinstance(attachments_data, list):
        raise TypeError("attachments must be a list")
    attachments = [Attachment(**a) for a in attachments_data]

    raw_links = data.get("links", [])
    if raw_links is not None and not isinstance(raw_links, list):
        raise TypeError("links must be a list")
    links = [str(link) for link in raw_links] if raw_links else []

    labels_data = data.get("labels", [])
    if labels_data is not None and not isinstance(labels_data, list):
        raise TypeError("labels must be a list")
    labels = list(labels_data or [])

    raw_revision = data.get("revision", 1)
    try:
        revision = int(raw_revision)
    except (TypeError, ValueError) as exc:
        raise TypeError("revision must be an integer") from exc
    if revision <= 0:
        raise ValueError("revision must be positive")

    return Requirement(
        id=data["id"],
        title=data["title"],
        statement=data["statement"],
        type=RequirementType(data["type"]),
        status=Status(data["status"]),
        owner=data["owner"],
        priority=Priority(data["priority"]),
        source=data["source"],
        verification=Verification(data["verification"]),
        acceptance=data.get("acceptance"),
        conditions=data.get("conditions", ""),
        rationale=data.get("rationale", ""),
        assumptions=data.get("assumptions", ""),
        modified_at=normalize_timestamp(data.get("modified_at")),
        labels=labels,
        attachments=attachments,
        revision=revision,
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
