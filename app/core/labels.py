"""Label definitions and in-memory CRUD helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(slots=True)
class Label:
    """Simple label with a ``name`` and associated ``color``."""

    name: str
    color: str


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
