from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Units,
    Verification,
)
from app.core.store import (
    ConflictError,
    filename_for,
    load,
    save,
    _existing_ids,
)


def sample() -> dict:
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


def test_save_and_load_roundtrip(tmp_path: Path):
    data = sample()
    path = save(tmp_path, data)
    assert path.name == filename_for(data["id"])
    loaded, mtime = load(path)
    assert loaded == data
    assert isinstance(mtime, float)


def test_conflict_detection(tmp_path: Path):
    data = sample()
    path = save(tmp_path, data)
    loaded, mtime = load(path)
    time.sleep(1)
    # simulate external modification to update mtime
    path.write_text(json.dumps(loaded))
    with pytest.raises(ConflictError):
        save(tmp_path, data, mtime=mtime)


def test_existing_ids_skips_invalid_and_excluded(tmp_path: Path):
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps({"id": "REQ-1"}))
    exclude = tmp_path / "exclude.json"
    exclude.write_text(json.dumps({"id": "REQ-2"}))
    bad = tmp_path / "bad.json"
    bad.write_text("{invalid json")

    ids = _existing_ids(tmp_path, exclude)
    assert ids == {"REQ-1"}


def test_save_accepts_dataclass(tmp_path: Path):
    req = Requirement(
        id="REQ-10",
        title="Dataclass", 
        statement="Save dataclass",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="user",
        priority=Priority.MEDIUM,
        source="spec",
        verification=Verification.ANALYSIS,
        acceptance="",
        units=Units(quantity="kg", nominal=1.0),
    )
    path = save(tmp_path, req)
    loaded, _ = load(path)
    assert loaded["id"] == req.id
    assert loaded["title"] == req.title
