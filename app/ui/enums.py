"""Common Enum definitions and label utilities for UI."""
from __future__ import annotations

from enum import Enum

from ..i18n import _
from ..core.model import RequirementType, Status, Priority, Verification


def _enum_label(e: Enum) -> str:
    """Convert enum member name to human-readable English label."""
    return e.name.replace("_", " ").lower().capitalize()


def enum_labels(enum_cls: type[Enum]) -> dict[str, str]:
    """Return mapping of enum values to localized labels."""
    return {e.value: _(_enum_label(e)) for e in enum_cls}


# Mapping of requirement field names to their Enum classes
ENUMS: dict[str, type[Enum]] = {
    "type": RequirementType,
    "status": Status,
    "priority": Priority,
    "verification": Verification,
}


# Pre-generated localized labels for each enumerated field
LABELS: dict[str, dict[str, str]] = {name: enum_labels(cls) for name, cls in ENUMS.items()}
