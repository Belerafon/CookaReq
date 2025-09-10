from app.core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
)


def test_requirement_defaults():
    req = Requirement(
        id="REQ-1",
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
