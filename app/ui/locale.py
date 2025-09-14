"""Localization helpers for requirement fields and enums."""
from __future__ import annotations

from ..i18n import _
from .enums import LABELS as EN_LABELS

# Backwards compatible aliases for enum label mappings
TYPE = EN_LABELS.get("type", {})
STATUS = EN_LABELS.get("status", {})
PRIORITY = EN_LABELS.get("priority", {})
VERIFICATION = EN_LABELS.get("verification", {})

# Human-readable labels for requirement fields
FIELD_LABELS = {
    "id": _("Requirement ID (number)"),
    "title": _("Short title"),
    "statement": _("Requirement text"),
    "acceptance": _("Acceptance criteria"),
    "conditions": _("Conditions"),
    "trace_up": _("Trace up"),
    "trace_down": _("Trace down"),
    "version": _("Requirement version"),
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
