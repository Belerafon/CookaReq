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
    required = [
        "id",
        "statement",
    ]
    for field in required:
        if field not in data:
            raise KeyError(f"missing required field: {field}")

    for field in ("text", "tags"):
        if field in data:
            raise KeyError(f"unsupported field: {field}")

    def _enum_value(field: str, enum_cls: type[Enum], default: Enum) -> Enum:
        value = data.get(field, default)
        if isinstance(value, enum_cls):
            return value
        if value in (None, ""):
            return default
        try:
            return enum_cls(value)
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value}") from exc

    def _text_value(field: str, default: str = "") -> str:
        value = data.get(field, default)
        if value is None:
            return default
        if isinstance(value, str):
            return value
        return str(value)

    attachments_data = data.get("attachments")
    if attachments_data in (None, ""):
        attachments_data = []
    if not isinstance(attachments_data, list):
        raise TypeError("attachments must be a list")
    attachments = [Attachment(**a) for a in attachments_data]

    raw_links = data.get("links")
    if raw_links in (None, ""):
        raw_links = []
    if raw_links and not isinstance(raw_links, list):
        raise TypeError("links must be a list")
    links = [str(link) for link in raw_links] if raw_links else []

    labels_data = data.get("labels")
    if labels_data in (None, ""):
        labels = []
    else:
        if not isinstance(labels_data, list):
            raise TypeError("labels must be a list")
        labels = list(labels_data)

    try:
        req_id = int(data["id"])
    except (TypeError, ValueError) as exc:
        raise TypeError("id must be an integer") from exc

    statement = data["statement"]
    if statement is None:
        raise TypeError("statement cannot be null")
    if not isinstance(statement, str):
        statement = str(statement)

    title = _text_value("title")

    owner = _text_value("owner")
    source = _text_value("source")
    conditions = _text_value("conditions")
    rationale = _text_value("rationale")
    assumptions = _text_value("assumptions")
    version = _text_value("version")
    notes = _text_value("notes")

    acceptance = data.get("acceptance")

    revision_raw = data.get("revision", 1)
    try:
        revision = int(revision_raw)
    except (TypeError, ValueError) as exc:
        raise TypeError("revision must be an integer") from exc

    modified_at = normalize_timestamp(data.get("modified_at"))
    approved_raw = data.get("approved_at")
    approved_at = normalize_timestamp(approved_raw) if approved_raw else None

    return Requirement(
        id=req_id,
        title=title,
        statement=statement,
        type=_enum_value("type", RequirementType, RequirementType.REQUIREMENT),
        status=_enum_value("status", Status, Status.DRAFT),
        owner=owner,
        priority=_enum_value("priority", Priority, Priority.MEDIUM),
        source=source,
        verification=_enum_value(
            "verification", Verification, Verification.ANALYSIS
        ),
        acceptance=acceptance,
        conditions=conditions,
        rationale=rationale,
        assumptions=assumptions,
        version=version,
        modified_at=modified_at,
        labels=labels,
        attachments=attachments,
        revision=revision,
        approved_at=approved_at,
        notes=notes,
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
