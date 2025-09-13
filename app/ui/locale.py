"""Localization helpers for enumerated fields using gettext."""

from ..i18n import _
from enum import Enum

from ..core.model import RequirementType, Status, Priority, Verification


def _enum_label(e: Enum) -> str:
    """Convert enum member name to human-readable English label."""
    return e.name.replace("_", " ").lower().capitalize()


# English labels generated from enum values
TYPE = {e.value: _(_enum_label(e)) for e in RequirementType}

STATUS = {e.value: _(_enum_label(e)) for e in Status}

PRIORITY = {e.value: _(_enum_label(e)) for e in Priority}

VERIFICATION = {e.value: _(_enum_label(e)) for e in Verification}

EN_LABELS = {
    "type": TYPE,
    "status": STATUS,
    "priority": PRIORITY,
    "verification": VERIFICATION,
}

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
    """Return localized label for given code."""
    return _(EN_LABELS.get(category, {}).get(code, code))


def label_to_code(category: str, label: str) -> str:
    """Return internal code for given localized label."""
    mapping = {_(lbl): code for code, lbl in EN_LABELS.get(category, {}).items()}
    return mapping.get(label, label)
