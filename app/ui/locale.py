"""Localization helpers for enumerated fields using gettext."""

from gettext import gettext as _

# English labels for enum values
TYPE = {
    "requirement": "Requirement",
    "constraint": "Constraint",
    "interface": "Interface",
}

STATUS = {
    "draft": "Draft",
    "in_review": "In review",
    "approved": "Approved",
    "baselined": "Baselined",
    "retired": "Retired",
}

PRIORITY = {
    "low": "Low",
    "medium": "Medium",
    "high": "High",
}

VERIFICATION = {
    "inspection": "Inspection",
    "analysis": "Analysis",
    "demonstration": "Demonstration",
    "test": "Test",
}

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
