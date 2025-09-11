import pytest
from app.core.validate import ValidationError, validate


def make_valid() -> dict:
    return {
        "id": "REQ-1",
        "title": "Title",
        "statement": "Statement",
        "type": "requirement",
        "status": "draft",
        "owner": "user",
        "priority": "medium",
        "source": "spec",
        "verification": "analysis",
        "revision": 1,
    }


def test_duplicate_id():
    data = make_valid()
    with pytest.raises(ValidationError):
        validate(data, existing_ids={"REQ-1"})


def test_acceptance_optional_for_verification_methods():
    data = make_valid()
    data["verification"] = "test"
    data.pop("acceptance", None)
    validate(data)


def test_acceptance_present_passes():
    data = make_valid()
    data["verification"] = "test"
    data["acceptance"] = "TST-1"
    validate(data)
