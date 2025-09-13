"""Tests for requirement ops."""

import pytest
from pathlib import Path

import app.mcp.tools_write as tools_write
from app.mcp.tools_write import (
    create_requirement,
    patch_requirement,
    delete_requirement,
    link_requirements,
)
from app.mcp.utils import ErrorCode
from app.core.store import load, filename_for


def _base_req(req_id: int) -> dict:
    return {
        "id": req_id,
        "title": "Title",
        "statement": "Statement",
        "type": "requirement",
        "status": "draft",
        "owner": "user",
        "priority": "medium",
        "source": "spec",
        "verification": "analysis",
        "units": {"quantity": "kg", "nominal": 1.0, "tolerance": 0.1},
        "attachments": [{"path": "a.txt", "note": "n"}],
        "approved_at": "2025-01-01",
        "notes": "note",
        "labels": [],
        "revision": 1,
    }


def test_create_patch_delete(tmp_path: Path):
    req = _base_req(1)
    create_requirement(tmp_path, req)
    path = tmp_path / filename_for(1)
    assert path.exists()

    # patch allowed field
    patch_requirement(tmp_path, 1, [{"op": "replace", "path": "/title", "value": "New"}], rev=1)
    data, _ = load(path)
    assert data["title"] == "New"
    assert data["revision"] == 2
    assert data["units"] == {"quantity": "kg", "nominal": 1.0, "tolerance": 0.1}
    assert data["attachments"] == [{"path": "a.txt", "note": "n"}]
    assert data["approved_at"] == "2025-01-01"
    assert data["notes"] == "note"

    # conflicting revision
    err = patch_requirement(tmp_path, 1, [{"op": "replace", "path": "/title", "value": "Other"}], rev=1)
    assert err["error"]["code"] == ErrorCode.CONFLICT

    # forbidden fields
    err = patch_requirement(tmp_path, 1, [{"op": "replace", "path": "/id", "value": 5}], rev=2)
    assert err["error"]["code"] == ErrorCode.VALIDATION_ERROR

    # delete with wrong revision
    err = delete_requirement(tmp_path, 1, rev=1)
    assert err["error"]["code"] == ErrorCode.CONFLICT
    assert path.exists()

    # delete with correct revision
    res = delete_requirement(tmp_path, 1, rev=2)
    assert res == {"id": 1}
    assert not path.exists()


def test_link_requirements(tmp_path: Path):
    create_requirement(tmp_path, _base_req(1))
    create_requirement(tmp_path, _base_req(2))

    # link
    link_requirements(tmp_path, source_id=1, derived_id=2, link_type="derived_from", rev=1)
    path = tmp_path / filename_for(2)
    data, _ = load(path)
    assert data["revision"] == 2
    assert data["derived_from"] == [{"source_id": 1, "source_revision": 1, "suspect": False}]

    # outdated rev
    err = link_requirements(tmp_path, source_id=1, derived_id=2, link_type="derived_from", rev=1)
    assert err["error"]["code"] == ErrorCode.CONFLICT

    # patching derived_from should be prohibited
    err = patch_requirement(tmp_path, 2, [{"op": "replace", "path": "/derived_from", "value": []}], rev=2)
    assert err["error"]["code"] == ErrorCode.VALIDATION_ERROR


def test_create_requirement_errors(tmp_path: Path, monkeypatch) -> None:
    from app.core.store import ConflictError

    def conflict(*args, **kwargs):  # noqa: ANN001, ANN002
        raise ConflictError("exists")

    monkeypatch.setattr("app.core.requirements.save_requirement", conflict)
    err = create_requirement(tmp_path, _base_req(1))
    assert err["error"]["code"] == ErrorCode.CONFLICT

    err = create_requirement(tmp_path, {"id": 2})
    assert err["error"]["code"] == ErrorCode.VALIDATION_ERROR

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002
        raise RuntimeError("boom")

    monkeypatch.setattr("app.core.requirements.save_requirement", boom)
    err = create_requirement(tmp_path, _base_req(3))
    assert err["error"]["code"] == ErrorCode.INTERNAL


def test_patch_requirement_errors(tmp_path: Path, monkeypatch) -> None:
    # not found
    err = patch_requirement(tmp_path, 1, [{"op": "replace", "path": "/title", "value": "X"}], rev=1)
    assert err["error"]["code"] == ErrorCode.NOT_FOUND

    create_requirement(tmp_path, _base_req(1))

    # invalid patch structure
    err = patch_requirement(tmp_path, 1, [{"path": "/title", "value": "Y"}], rev=1)
    assert err["error"]["code"] == ErrorCode.VALIDATION_ERROR

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002
        raise RuntimeError("boom")

    monkeypatch.setattr("app.core.requirements.save_requirement", boom)
    err = patch_requirement(tmp_path, 1, [{"op": "replace", "path": "/title", "value": "X"}], rev=1)
    assert err["error"]["code"] == ErrorCode.INTERNAL


def test_delete_requirement_errors(tmp_path: Path, monkeypatch) -> None:
    err = delete_requirement(tmp_path, 1, rev=1)
    assert err["error"]["code"] == ErrorCode.NOT_FOUND

    create_requirement(tmp_path, _base_req(1))

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002
        raise RuntimeError("boom")

    monkeypatch.setattr("app.core.requirements.delete_requirement", boom)
    err = delete_requirement(tmp_path, 1, rev=1)
    assert err["error"]["code"] == ErrorCode.INTERNAL


def test_link_requirements_errors(tmp_path: Path, monkeypatch) -> None:
    # missing source
    create_requirement(tmp_path, _base_req(2))
    err = link_requirements(tmp_path, source_id=1, derived_id=2, link_type="derived_from", rev=1)
    assert err["error"]["code"] == ErrorCode.NOT_FOUND

    # missing derived
    create_requirement(tmp_path, _base_req(1))
    err = link_requirements(tmp_path, source_id=1, derived_id=3, link_type="derived_from", rev=1)
    assert err["error"]["code"] == ErrorCode.NOT_FOUND

    def val_err(*args, **kwargs):  # noqa: ANN001, ANN002
        raise ValueError("bad")

    orig = tools_write.requirement_from_dict
    monkeypatch.setattr(tools_write, "requirement_from_dict", val_err)
    err = link_requirements(tmp_path, source_id=1, derived_id=2, link_type="derived_from", rev=1)
    assert err["error"]["code"] == ErrorCode.VALIDATION_ERROR

    monkeypatch.setattr(tools_write, "requirement_from_dict", orig)

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002
        raise RuntimeError("boom")

    monkeypatch.setattr("app.core.requirements.save_requirement", boom)
    err = link_requirements(tmp_path, source_id=1, derived_id=2, link_type="derived_from", rev=1)
    assert err["error"]["code"] == ErrorCode.INTERNAL

    err = link_requirements(tmp_path, source_id=1, derived_id=2, link_type="bogus", rev=1)
    assert err["error"]["code"] == ErrorCode.VALIDATION_ERROR


def test_link_requirements_types(tmp_path: Path) -> None:
    for i in range(1, 7):
        create_requirement(tmp_path, _base_req(i))

    link_requirements(tmp_path, source_id=1, derived_id=2, link_type="parent", rev=1)
    data, _ = load(tmp_path / filename_for(2))
    assert data["parent"] == {"source_id": 1, "source_revision": 1, "suspect": False}
    assert data["revision"] == 2

    link_requirements(tmp_path, source_id=3, derived_id=4, link_type="verifies", rev=1)
    data, _ = load(tmp_path / filename_for(4))
    assert data["links"]["verifies"] == [{"source_id": 3, "source_revision": 1, "suspect": False}]
    assert data["revision"] == 2

    link_requirements(tmp_path, source_id=5, derived_id=6, link_type="relates", rev=1)
    data, _ = load(tmp_path / filename_for(6))
    assert data["links"]["relates"] == [{"source_id": 5, "source_revision": 1, "suspect": False}]
    assert data["revision"] == 2


def test_patch_parent_and_links_forbidden(tmp_path: Path) -> None:
    create_requirement(tmp_path, _base_req(1))
    create_requirement(tmp_path, _base_req(2))
    link_requirements(tmp_path, source_id=1, derived_id=2, link_type="parent", rev=1)
    err = patch_requirement(
        tmp_path, 2, [{"op": "replace", "path": "/parent", "value": None}], rev=2
    )
    assert err["error"]["code"] == ErrorCode.VALIDATION_ERROR

    create_requirement(tmp_path, _base_req(3))
    create_requirement(tmp_path, _base_req(4))
    link_requirements(tmp_path, source_id=3, derived_id=4, link_type="verifies", rev=1)
    err = patch_requirement(
        tmp_path, 4, [{"op": "replace", "path": "/links", "value": {}}], rev=2
    )
    assert err["error"]["code"] == ErrorCode.VALIDATION_ERROR
