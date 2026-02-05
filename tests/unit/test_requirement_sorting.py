"""Tests for card export requirement sorting."""

from __future__ import annotations

from app.core.model import Priority, Requirement, RequirementType, Status, Verification
from app.core.requirement_sorting import sort_requirements_for_cards


def _make_requirement(
    req_id: int,
    *,
    title: str,
    source: str,
    labels: list[str],
) -> Requirement:
    return Requirement(
        id=req_id,
        title=title,
        statement=f"Statement {req_id}",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="",
        priority=Priority.MEDIUM,
        source=source,
        verification=Verification.NOT_DEFINED,
        labels=labels,
    )


def test_sort_requirements_for_cards_by_labels():
    reqs = [
        _make_requirement(3, title="c", source="z", labels=[]),
        _make_requirement(2, title="b", source="y", labels=["beta", "alpha"]),
        _make_requirement(1, title="a", source="x", labels=["alpha"]),
    ]

    sorted_reqs = sort_requirements_for_cards(reqs, sort_mode="labels")

    assert [req.id for req in sorted_reqs] == [1, 2, 3]


def test_sort_requirements_for_cards_by_source_and_title():
    reqs = [
        _make_requirement(4, title="Gamma", source="Spec B", labels=[]),
        _make_requirement(2, title="Alpha", source="Spec A", labels=[]),
        _make_requirement(3, title="Beta", source="Spec A", labels=[]),
    ]

    by_source = sort_requirements_for_cards(reqs, sort_mode="source")
    assert [req.id for req in by_source] == [2, 3, 4]

    by_title = sort_requirements_for_cards(reqs, sort_mode="title")
    assert [req.id for req in by_title] == [2, 3, 4]
