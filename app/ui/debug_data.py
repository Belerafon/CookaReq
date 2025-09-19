"""Static dataset feeding the debug requirement lists."""

from __future__ import annotations

from typing import Iterable

from ..core.model import Priority, Requirement, RequirementType, Status, Verification


DEBUG_LIST_FIELDS: tuple[str, ...] = ("status", "owner")

_DEBUG_REQUIREMENTS_DATA: tuple[tuple[int, str, Status, str, str], ...] = (
    (
        10_001,
        "Debug requirement A",
        Status.DRAFT,
        "Alpha",
        "Static debug row one",
    ),
    (
        10_002,
        "Debug requirement B",
        Status.IN_REVIEW,
        "Beta",
        "Static debug row two",
    ),
    (
        10_003,
        "Debug requirement C",
        Status.APPROVED,
        "Gamma",
        "Static debug row three",
    ),
)


def build_debug_requirements(source: Iterable[tuple[int, str, Status, str, str]] | None = None) -> list[Requirement]:
    """Return a list of :class:`Requirement` populated with static debug data."""

    rows = list(source) if source is not None else list(_DEBUG_REQUIREMENTS_DATA)
    dataset: list[Requirement] = []
    for req_id, title, status, owner, statement in rows:
        dataset.append(
            Requirement(
                id=req_id,
                title=title,
                statement=statement,
                type=RequirementType.REQUIREMENT,
                status=status,
                owner=owner,
                priority=Priority.MEDIUM,
                source="debug-static",
                verification=Verification.ANALYSIS,
            )
        )
    return dataset
