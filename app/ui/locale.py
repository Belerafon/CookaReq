"""Localization helpers for requirement fields and enums."""

from __future__ import annotations

from ..i18n import _
from .enums import LABELS as EN_LABELS

# Human-readable labels for requirement fields (msgids only)
FIELD_LABEL_MSGIDS = {
    "id": "Requirement ID (number)",
    "title": "Short title",
    "statement": "Requirement text",
    "acceptance": "Acceptance criteria",
    "conditions": "Conditions",
    "revision": "Requirement revision",
    "modified_at": "Modified at",
    "owner": "Owner",
    "source": "Source",
    "type": "Requirement type",
    "status": "Status",
    "priority": "Priority",
    "verification": "Verification method",
    "rationale": "Rationale",
    "assumptions": "Assumptions",
    "labels": "Labels",
    "derived_count": "Derived count",
    "derived_from": "Derived from",
    "attachments": "Attachments",
    "approved_at": "Approved at",
    "notes": "Notes",
    "links": "Links",
    "doc_prefix": "Document prefix",
    "rid": "Requirement RID",
}


def _build_field_labels() -> dict[str, str]:
    return {name: _(msgid) for name, msgid in FIELD_LABEL_MSGIDS.items()}


FIELD_LABELS = _build_field_labels()


def field_label(name: str) -> str:
    """Return localized label for requirement field name."""
    if not name:
        return ""
    msgid = FIELD_LABEL_MSGIDS.get(name.casefold())
    if msgid is not None:
        return _(msgid)
    cleaned = name.replace("_", " ").strip()
    if not cleaned:
        return ""
    return _(cleaned.capitalize())


def code_to_label(category: str, code: str) -> str:
    """Return localized label for given enum code."""
    return EN_LABELS.get(category, {}).get(code, code)


def label_to_code(category: str, label: str) -> str:
    """Return internal code for given localized label."""
    mapping = {lbl: code for code, lbl in EN_LABELS.get(category, {}).items()}
    return mapping.get(label, label)
