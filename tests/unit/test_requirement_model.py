"""Tests for requirement model."""

import pytest
from app.ui.requirement_model import RequirementModel
from app.core.model import Requirement, RequirementType, Status, Priority, Verification


def _req(id: int, status: Status) -> Requirement:
    return Requirement(
        id=id,
        title="T",
        statement="S",
        type=RequirementType.REQUIREMENT,
        status=status,
        owner="o",
        priority=Priority.MEDIUM,
        source="s",
        verification=Verification.ANALYSIS,
    )


def test_status_filter():
    model = RequirementModel()
    model.set_requirements([_req(1, Status.DRAFT), _req(2, Status.APPROVED)])
    assert [r.id for r in model.get_visible()] == [1, 2]
    model.set_status("approved")
    assert [r.id for r in model.get_visible()] == [2]
    model.set_status(None)
    assert [r.id for r in model.get_visible()] == [1, 2]
