"""Label definitions, preset sets and in-memory CRUD helpers."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Dict, List


@dataclass(slots=True)
class Label:
    """Simple label with a ``name`` and associated ``color``."""

    name: str
    color: str


def _color_from_name(name: str) -> str:
    """Generate a stable pastel color from ``name``."""
    digest = sha1(name.encode("utf-8")).hexdigest()
    r = (int(digest[0:2], 16) + 0xAA) // 2
    g = (int(digest[2:4], 16) + 0xAA) // 2
    b = (int(digest[4:6], 16) + 0xAA) // 2
    return f"#{r:02x}{g:02x}{b:02x}"


def _preset(names: List[str]) -> List[Label]:
    return [Label(n, _color_from_name(n)) for n in names]


PRESET_SETS: Dict[str, List[Label]] = {
    "basic": _preset([
        "functional",
        "non-functional",
        "ui",
        "performance",
        "reliability",
        "safety",
        "security",
        "usability",
        "constraint",
        "regulatory",
    ]),
    "role": _preset([
        "system",
        "software",
        "hardware",
        "integration",
        "test",
    ]),
    "status": _preset([
        "draft",
        "approved",
        "in-progress",
        "implemented",
        "verified",
        "obsolete",
    ]),
    "priority": _preset([
        "high",
        "medium",
        "low",
    ]),
    "additional": _preset([
        "critical",
        "derived",
        "untested",
        "suspect-link",
        "attachments",
    ]),
}

PRESET_SET_TITLES: Dict[str, str] = {
    "basic": "Basic",
    "role": "By role",
    "status": "By status",
    "priority": "By priority",
    "additional": "Additional",
}


def add_label(labels: List[Label], label: Label) -> None:
    """Add ``label`` to ``labels`` ensuring unique names."""
    if any(l.name == label.name for l in labels):
        raise ValueError(f"label exists: {label.name}")
    labels.append(label)


def get_label(labels: List[Label], name: str) -> Label | None:
    """Return label with ``name`` or ``None`` if absent."""
    for lbl in labels:
        if lbl.name == name:
            return lbl
    return None


def update_label(labels: List[Label], label: Label) -> None:
    """Replace existing label with same name as ``label``.

    Raises
    ------
    KeyError
        If label with given name is not found.
    """
    for i, existing in enumerate(labels):
        if existing.name == label.name:
            labels[i] = label
            return
    raise KeyError(f"label not found: {label.name}")


def delete_label(labels: List[Label], name: str) -> None:
    """Remove label with ``name`` from ``labels``.

    Raises
    ------
    KeyError
        If no label with ``name`` exists.
    """
    for i, lbl in enumerate(labels):
        if lbl.name == name:
            del labels[i]
            return
    raise KeyError(f"label not found: {name}")
