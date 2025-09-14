"""Tests for validate."""

import json

import pytest

from app.core.store import load_index
from app.core.validate import ValidationError, validate

pytestmark = pytest.mark.unit


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


def write_req(directory, req_id, **extra):
    req = make_valid()
    req["id"] = req_id
    req.update(extra)
    (directory / f"{req_id}.json").write_text(json.dumps(req))


def test_duplicate_id(tmp_path):
    write_req(tmp_path, 1)
    data = make_valid()
    existing_ids = set(load_index(tmp_path))
    with pytest.raises(ValidationError):
        validate(data, tmp_path, existing_ids=existing_ids)


def test_acceptance_optional_for_verification_methods(tmp_path):
    data = make_valid()
    data["verification"] = "test"
    data.pop("acceptance", None)
    validate(data, tmp_path)


def test_acceptance_present_passes(tmp_path):
    data = make_valid()
    data["verification"] = "test"
    data["acceptance"] = "TST-1"
    validate(data, tmp_path)


def test_self_reference(tmp_path):
    data = make_valid()
    data["derived_from"] = [{"source_id": 1, "source_revision": 1, "suspect": False}]
    with pytest.raises(ValidationError):
        validate(data, tmp_path)


def test_missing_source_id(tmp_path):
    data = make_valid()
    data["id"] = 2
    data["derived_from"] = [{"source_id": 1, "source_revision": 1, "suspect": False}]
    with pytest.raises(ValidationError):
        validate(data, tmp_path)


def test_cycle_detection(tmp_path):
    write_req(tmp_path, 1, derived_from=[{"source_id": 2, "source_revision": 1, "suspect": False}])
    data = make_valid()
    data["id"] = 2
    data["derived_from"] = [{"source_id": 1, "source_revision": 1, "suspect": False}]
    with pytest.raises(ValidationError):
        validate(data, tmp_path)


def test_valid_reference_passes(tmp_path):
    write_req(tmp_path, 1)
    data = make_valid()
    data["id"] = 2
    data["derived_from"] = [{"source_id": 1, "source_revision": 1, "suspect": False}]
    validate(data, tmp_path)
