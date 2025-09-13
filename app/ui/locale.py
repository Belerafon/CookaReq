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


def code_to_label(category: str, code: str) -> str:
    """Return localized label for given code."""
    return _(EN_LABELS.get(category, {}).get(code, code))


def label_to_code(category: str, label: str) -> str:
    """Return internal code for given localized label."""
    mapping = {_(lbl): code for code, lbl in EN_LABELS.get(category, {}).items()}
    return mapping.get(label, label)
