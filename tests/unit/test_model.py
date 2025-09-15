"""Tests for model."""

import pytest

from app.core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
    requirement_from_dict,
    requirement_to_dict,
)

pytestmark = pytest.mark.unit


def test_requirement_defaults():
    req = Requirement(
        id=1,
        title="Title",
        statement="Statement",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="user",
        priority=Priority.MEDIUM,
        source="spec",
        verification=Verification.ANALYSIS,
    )
    assert req.revision == 1
    assert req.labels == []
    assert req.attachments == []
    assert req.approved_at is None
    assert req.notes == ""
    assert req.conditions == ""
    assert req.version == ""
    assert req.modified_at == ""


def test_requirement_prefix_and_rid():
    data = {
        "id": 5,
        "title": "T",
        "statement": "S",
        "type": "requirement",
        "status": "draft",
        "owner": "o",
        "priority": "medium",
        "source": "s",
        "verification": "analysis",
    }
    req = requirement_from_dict(data, doc_prefix="SYS", rid="SYS005")
    assert req.doc_prefix == "SYS"
    assert req.rid == "SYS005"
    roundtrip = requirement_to_dict(req)
    assert "doc_prefix" not in roundtrip
    assert "rid" not in roundtrip
