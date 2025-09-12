import pytest
from pathlib import Path

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
        "labels": [],
        "revision": 1,
    }


def test_create_patch_delete(tmp_path: Path):
    req = _base_req(1)
    create_requirement(tmp_path, req)
    path = tmp_path / filename_for(1)
    assert path.exists()

    # patch allowed field
    patch_requirement(tmp_path, 1, {"title": "New"}, rev=1)
    data, _ = load(path)
    assert data["title"] == "New"
    assert data["revision"] == 2

    # conflicting revision
    err = patch_requirement(tmp_path, 1, {"title": "Other"}, rev=1)
    assert err["error"]["code"] == ErrorCode.CONFLICT

    # forbidden fields
    err = patch_requirement(tmp_path, 1, {"id": 5}, rev=2)
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
    link_requirements(tmp_path, source_id=1, derived_id=2, rev=1)
    path = tmp_path / filename_for(2)
    data, _ = load(path)
    assert data["revision"] == 2
    assert data["derived_from"] == [{"source_id": 1, "source_revision": 1, "suspect": False}]

    # outdated rev
    err = link_requirements(tmp_path, source_id=1, derived_id=2, rev=1)
    assert err["error"]["code"] == ErrorCode.CONFLICT

    # patching derived_from should be prohibited
    err = patch_requirement(tmp_path, 2, {"derived_from": []}, rev=2)
    assert err["error"]["code"] == ErrorCode.VALIDATION_ERROR
