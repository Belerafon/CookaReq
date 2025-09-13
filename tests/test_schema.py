"""Tests for schema."""

import pytest

from app.core.schema import validate


def make_valid() -> dict:
    return {
        "id": 1,
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


def test_validate_accepts_valid():
    validate(make_valid())


def test_validate_rejects_missing_field():
    data = make_valid()
    del data["id"]
    with pytest.raises(ValueError):
        validate(data)


def test_validate_rejects_bad_enum():
    data = make_valid()
    data["type"] = "bad"
    with pytest.raises(ValueError):
        validate(data)


def test_derived_from_and_derivation_valid():
    data = make_valid()
    data["derived_from"] = [
        {"source_id": 2, "source_revision": 1, "suspect": True}
    ]
    data["derivation"] = {
        "rationale": "r",
        "assumptions": ["a"],
        "method": "m",
        "margin": "10%",
    }
    validate(data)


def test_derived_from_missing_field():
    data = make_valid()
    data["derived_from"] = [{"source_id": 2}]
    with pytest.raises(ValueError):
        validate(data)


def test_derivation_missing_field():
    data = make_valid()
    data["derivation"] = {
        "rationale": "r",
        "assumptions": ["a"],
        "method": "m",
    }
    with pytest.raises(ValueError):
        validate(data)
