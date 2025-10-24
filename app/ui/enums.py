"""Common Enum definitions and label utilities for UI."""

from __future__ import annotations

from enum import Enum

from ..core.model import Priority, RequirementType, Status, Verification


def _enum_label(e: Enum) -> str:
    """Convert enum member name to human-readable English label."""
    return e.name.replace("_", " ").lower().capitalize()


def enum_label_msgids(enum_cls: type[Enum]) -> dict[str, str]:
    """Return mapping of enum values to their message identifiers."""
    return {e.value: _enum_label(e) for e in enum_cls}


# Mapping of requirement field names to their Enum classes
ENUMS: dict[str, type[Enum]] = {
    "type": RequirementType,
    "status": Status,
    "priority": Priority,
    "verification": Verification,
}


# Pre-generated message identifiers for each enumerated field
LABEL_MSGIDS: dict[str, dict[str, str]] = {
    name: enum_label_msgids(cls) for name, cls in ENUMS.items()
}
