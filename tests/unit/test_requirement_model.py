"""Tests for requirement model."""

import pytest

from app.core.model import Priority, Requirement, RequirementType, Status, Verification
from app.ui.requirement_model import RequirementModel

pytestmark = pytest.mark.unit


def _req(req_id: int, status: Status) -> Requirement:
    return Requirement(
        id=req_id,
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
