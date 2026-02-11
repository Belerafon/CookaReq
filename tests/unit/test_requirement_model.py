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


def test_unsaved_tracking():
    model = RequirementModel()
    req = _req(1, Status.DRAFT)
    req.doc_prefix = "DOC"
    model.set_requirements([req])

    assert model.is_unsaved(req) is False
    model.mark_unsaved(req)
    assert model.is_unsaved(req) is True

    assert model.clear_unsaved(req) is True
    assert model.is_unsaved(req) is False


def test_delete_scoped_to_document_prefix():
    model = RequirementModel()
    req_primary = _req(1, Status.DRAFT)
    req_primary.doc_prefix = "REQ"
    req_other = _req(1, Status.APPROVED)
    req_other.doc_prefix = "ALT"
    model.set_requirements([req_primary, req_other])

    model.mark_unsaved(req_primary)
    model.mark_unsaved(req_other)

    model.delete(1, doc_prefix="REQ")

    remaining = model.get_all()
    assert len(remaining) == 1
    assert remaining[0].doc_prefix == "ALT"
    assert model.is_unsaved(req_id=1, prefix="REQ") is False
    assert model.is_unsaved(req_id=1, prefix="ALT") is True
