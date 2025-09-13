"""Tests for model."""

from app.core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
    requirement_from_dict,
    requirement_to_dict,
)


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
    assert req.units is None
    assert req.approved_at is None
    assert req.notes == ""
    assert req.conditions == ""
    assert req.trace_up == ""
    assert req.trace_down == ""
    assert req.version == ""
    assert req.modified_at == ""
    assert req.derived_from == []
    assert req.derivation is None


def test_requirement_derivation_conversion():
    data = {
        "id": 1,
        "title": "Title",
        "statement": "Statement",
        "type": "requirement",
        "status": "draft",
        "owner": "user",
        "priority": "medium",
        "source": "spec",
        "verification": "analysis",
        "derived_from": [
            {"source_id": 2, "source_revision": 3, "suspect": True}
        ],
        "derivation": {
            "rationale": "r",
            "assumptions": ["a1", "a2"],
            "method": "m",
            "margin": "10%",
        },
    }
    req = requirement_from_dict(data)
    assert req.derived_from[0].source_id == 2
    assert req.derived_from[0].suspect is True
    assert req.derivation.margin == "10%"
    roundtrip = requirement_to_dict(req)
    assert roundtrip["derived_from"][0]["source_revision"] == 3
    assert roundtrip["derivation"]["assumptions"] == ["a1", "a2"]
