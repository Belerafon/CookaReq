"""Domain models for requirements."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any
from collections.abc import Mapping, Sequence

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
    REJECTED = "rejected"
    DEFERRED = "deferred"
    SUPERSEDED = "superseded"
    NEEDS_CLARIFICATION = "needs_clarification"


class Priority(str, Enum):
    """Enumerate requirement priority levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Verification(str, Enum):
    """Enumerate possible verification methods."""

    NOT_DEFINED = "not_defined"
    INSPECTION = "inspection"
    ANALYSIS = "analysis"
    DEMONSTRATION = "demonstration"
    TEST = "test"


@dataclass(slots=True)
class Attachment:
    """Represent a file attached to a requirement."""

    id: str
    path: str
    note: str = ""

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Attachment:
        """Create an :class:`Attachment` from a JSON mapping."""
        if not isinstance(data, Mapping):
            raise TypeError("attachment must be a mapping")
        try:
            attachment_id_raw = data["id"]
            path_raw = data["path"]
        except KeyError as exc:  # pragma: no cover - defensive
            raise TypeError("attachment mapping missing required fields") from exc
        attachment_id = str(attachment_id_raw).strip()
        if not attachment_id:
            raise TypeError("attachment id cannot be empty")
        note_raw = data.get("note", "")
        path = str(path_raw)
        note = "" if note_raw is None else str(note_raw)
        return cls(id=attachment_id, path=path, note=note)

    def to_mapping(self) -> dict[str, Any]:
        """Serialise the attachment for JSON storage."""
        return {"id": self.id, "path": self.path, "note": self.note}


@dataclass(slots=True)
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
    links: list[Link] = field(default_factory=list)
    # document-related metadata
    doc_prefix: str = ""
    rid: str = ""

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, Any],
        *,
        doc_prefix: str = "",
        rid: str = "",
    ) -> Requirement:
        """Create a requirement instance from JSON-compatible mapping."""
        if not isinstance(data, Mapping):
            raise TypeError("requirement payload must be a mapping")

        required = ["id", "statement"]
        for required_field in required:
            if required_field not in data:
                raise KeyError(f"missing required field: {required_field}")

        for legacy_field in ("text", "tags"):
            if legacy_field in data:
                raise KeyError(f"unsupported field: {legacy_field}")

        def _enum_value(field: str, enum_cls: type[Enum], default: Enum) -> Enum:
            value = data.get(field, default)
            if isinstance(value, enum_cls):
                return value
            if value in (None, ""):
                return default
            try:
                return enum_cls(value)
            except ValueError as exc:
                allowed = ", ".join(member.value for member in enum_cls)
                raise ValueError(
                    f"invalid {field}: {value!r}; expected one of: {allowed}"
                ) from exc

        def _text_value(field: str, default: str = "") -> str:
            value = data.get(field, default)
            if value is None:
                return default
            if isinstance(value, str):
                return value
            return str(value)

        attachments_data = data.get("attachments")
        if attachments_data in (None, ""):
            attachments_source: Sequence[Any] = []
        else:
            attachments_source = attachments_data  # type: ignore[assignment]
        if isinstance(attachments_source, (str, bytes)) or not isinstance(
            attachments_source, Sequence
        ):
            raise TypeError("attachments must be a list")
        attachments: list[Attachment] = []
        for entry in attachments_source:
            if isinstance(entry, Attachment):
                attachments.append(entry)
            else:
                attachments.append(Attachment.from_mapping(entry))
        seen_attachment_ids: set[str] = set()
        for attachment in attachments:
            if attachment.id in seen_attachment_ids:
                raise ValueError("attachment ids must be unique")
            seen_attachment_ids.add(attachment.id)

        raw_links = data.get("links")
        links: list[Link] = []
        if raw_links in (None, ""):
            raw_links = []
        if raw_links:
            if not isinstance(raw_links, list):
                raise TypeError("links must be a list")
            for entry in raw_links:
                if isinstance(entry, Link):
                    links.append(entry)
                    continue
                try:
                    link = Link.from_raw(entry)
                except (TypeError, ValueError) as exc:
                    raise TypeError("invalid link entry") from exc
                links.append(link)

        labels_data = data.get("labels")
        if labels_data in (None, ""):
            labels = []
        else:
            if not isinstance(labels_data, list):
                raise TypeError("labels must be a list")
            labels = [str(label) for label in labels_data]

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
        notes = _text_value("notes")

        acceptance_raw = data.get("acceptance")
        if acceptance_raw is None:
            acceptance = None
        elif isinstance(acceptance_raw, str):
            acceptance = acceptance_raw
        else:
            acceptance = str(acceptance_raw)

        revision_raw = data.get("revision", 1)
        try:
            revision = int(revision_raw)
        except (TypeError, ValueError) as exc:
            raise TypeError("revision must be an integer") from exc
        if revision <= 0:
            raise ValueError("revision must be positive")

        modified_at = normalize_timestamp(data.get("modified_at"))
        approved_raw = data.get("approved_at")
        approved_at = normalize_timestamp(approved_raw) if approved_raw else None

        return cls(
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
            modified_at=modified_at,
            labels=labels,
            attachments=attachments,
            revision=revision,
            approved_at=approved_at,
            notes=notes,
            links=links,
            doc_prefix=str(doc_prefix),
            rid=str(rid),
        )

    def to_mapping(self) -> dict[str, Any]:
        """Serialise the requirement into JSON-compatible mapping."""
        data = asdict(self)
        data.pop("doc_prefix", None)
        data.pop("rid", None)
        if data.get("links"):
            links: list[dict[str, Any]] = []
            for link in self.links:
                if isinstance(link, Link):
                    links.append(link.to_dict())
                else:  # pragma: no cover - defensive
                    links.append({"rid": str(link)})
            if links:
                data["links"] = links
            else:
                data.pop("links", None)
        else:
            data.pop("links", None)
        attachments_payload: list[dict[str, Any]] = []
        for attachment in self.attachments:
            if isinstance(attachment, Attachment):
                attachments_payload.append(attachment.to_mapping())
            elif isinstance(attachment, Mapping):  # pragma: no cover - defensive
                attachments_payload.append(dict(attachment))
            else:  # pragma: no cover - defensive
                attachments_payload.append({"path": str(attachment)})
        data["attachments"] = attachments_payload
        for key in ("type", "status", "priority", "verification"):
            value = data.get(key)
            if isinstance(value, Enum):
                data[key] = value.value
        return data


FINGERPRINT_FIELDS = (
    "title",
    "statement",
    "conditions",
    "rationale",
    "assumptions",
    "acceptance",
)


def _fingerprint_value(payload: Requirement | Mapping[str, Any], field: str) -> str:
    if isinstance(payload, Mapping):
        value = payload.get(field, "")
    else:
        value = getattr(payload, field, "")
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def requirement_fingerprint(payload: Requirement | Mapping[str, Any]) -> str:
    """Compute fingerprint for ``payload`` based on key textual fields."""
    data = {field: _fingerprint_value(payload, field) for field in FINGERPRINT_FIELDS}
    serialized = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


@dataclass
class Link:
    """Represent relationship to a parent requirement."""

    rid: str
    fingerprint: str | None = None
    suspect: bool = False

    @classmethod
    def from_raw(cls, raw: Any) -> Link:
        """Create :class:`Link` from ``raw`` representation."""
        if isinstance(raw, str):
            rid = raw.strip()
            if not rid:
                raise ValueError("link rid cannot be empty")
            return cls(rid=rid)
        if isinstance(raw, Mapping):
            rid = raw.get("rid")
            if not isinstance(rid, str) or not rid.strip():
                raise ValueError("link entry missing rid")
            rid = rid.strip()
            fingerprint_raw = raw.get("fingerprint")
            if fingerprint_raw in (None, ""):
                fingerprint = None
            elif isinstance(fingerprint_raw, str):
                fingerprint = fingerprint_raw
            else:
                fingerprint = str(fingerprint_raw)
            suspect_raw = raw.get("suspect", False)
            if isinstance(suspect_raw, bool):
                suspect = suspect_raw
            elif isinstance(suspect_raw, (int, float)):
                suspect = bool(suspect_raw)
            elif isinstance(suspect_raw, str):
                suspect = suspect_raw.strip().lower() in {"1", "true", "yes", "on"}
            else:
                suspect = bool(suspect_raw)
            return cls(rid=rid, fingerprint=fingerprint, suspect=suspect)
        raise TypeError("link entry must be a string or mapping")

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-friendly representation of the link."""
        data: dict[str, Any] = {"rid": self.rid}
        if self.fingerprint:
            data["fingerprint"] = self.fingerprint
        if self.suspect:
            data["suspect"] = self.suspect
        return data
