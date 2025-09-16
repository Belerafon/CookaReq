"""Tests for model."""

import pytest

from app.core.model import (
    Attachment,
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
    assert req.rationale == ""
    assert req.assumptions == ""
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


def test_requirement_from_dict_missing_metadata_defaults():
    data = {
        "id": "7",
        "statement": "Legacy statement",
    }
    req = requirement_from_dict(data)
    assert req.id == 7
    assert req.title == ""
    assert req.type is RequirementType.REQUIREMENT
    assert req.status is Status.DRAFT
    assert req.owner == ""
    assert req.priority is Priority.MEDIUM
    assert req.source == ""
    assert req.verification is Verification.ANALYSIS
    assert req.labels == []
    assert req.links == []
    assert req.revision == 1


def test_requirement_extended_roundtrip():
    req = Requirement(
        id=7,
        title="T",
        statement="S",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="o",
        priority=Priority.MEDIUM,
        source="s",
        verification=Verification.ANALYSIS,
        attachments=[Attachment(path="doc.txt", note="ref")],
        approved_at="2024-01-01 00:00:00",
        notes="extra",
        rationale="because",
        assumptions="if ready",
    )
    data = requirement_to_dict(req)
    assert data["attachments"][0]["path"] == "doc.txt"
    assert data["approved_at"] == "2024-01-01 00:00:00"
    assert "acceptance" in data and data["acceptance"] is None
    assert data["rationale"] == "because"
    assert data["assumptions"] == "if ready"
    again = requirement_from_dict(data)
    assert again.attachments[0].note == "ref"
    assert again.approved_at == "2024-01-01 00:00:00"
    assert again.notes == "extra"
    assert again.rationale == "because"
    assert again.assumptions == "if ready"


def test_requirement_from_dict_missing_statement():
    data = {
        "id": 1,
        "title": "T",
        "type": "requirement",
        "status": "draft",
        "owner": "o",
        "priority": "medium",
        "source": "s",
        "verification": "analysis",
    }
    with pytest.raises(KeyError):
        requirement_from_dict(data)


def test_requirement_from_dict_rejects_text_field():
    data = {
        "id": 1,
        "title": "T",
        "text": "legacy",
        "type": "requirement",
        "status": "draft",
        "owner": "o",
        "priority": "medium",
        "source": "s",
        "verification": "analysis",
    }
    with pytest.raises(KeyError):
        requirement_from_dict(data)


def test_requirement_from_dict_rejects_invalid_revision():
    data = {
        "id": 1,
        "statement": "S",
        "revision": "beta",
    }
    with pytest.raises(TypeError):
        requirement_from_dict(data)
