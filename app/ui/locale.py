"""Localization helpers for requirement fields and enums."""

from __future__ import annotations

from ..i18n import _
from .enums import LABELS as EN_LABELS

# Human-readable labels for requirement fields
FIELD_LABELS = {
    "id": _("Requirement ID (number)"),
    "title": _("Short title"),
    "statement": _("Requirement text"),
    "acceptance": _("Acceptance criteria"),
    "conditions": _("Conditions"),
    "revision": _("Requirement revision"),
    "modified_at": _("Modified at"),
    "owner": _("Owner"),
    "source": _("Source"),
    "type": _("Requirement type"),
    "status": _("Status"),
    "priority": _("Priority"),
    "verification": _("Verification method"),
    "rationale": _("Rationale"),
    "assumptions": _("Assumptions"),
    "labels": _("Labels"),
    "derived_count": _("Derived count"),
    "derived_from": _("Derived from"),
    "attachments": _("Attachments"),
    "approved_at": _("Approved at"),
    "notes": _("Notes"),
    "links": _("Links"),
    "doc_prefix": _("Document prefix"),
    "rid": _("Requirement RID"),
}


def field_label(name: str) -> str:
    """Return localized label for requirement field name."""
    label = FIELD_LABELS.get(name)
    if label is not None:
        return label
    return _(name.replace("_", " ").capitalize())


def code_to_label(category: str, code: str) -> str:
    """Return localized label for given enum code."""
    return EN_LABELS.get(category, {}).get(code, code)


def label_to_code(category: str, label: str) -> str:
    """Return internal code for given localized label."""
    mapping = {lbl: code for code, lbl in EN_LABELS.get(category, {}).items()}
    return mapping.get(label, label)
