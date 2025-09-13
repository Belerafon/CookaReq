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
    delete,
    _scan_ids,
)


def sample(req_id: int = 1) -> dict:
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
        "revision": 1,
        "units": {"quantity": "kg", "nominal": 1.0, "tolerance": 0.1},
        "attachments": [{"path": "a.txt", "note": "n"}],
        "approved_at": "2025-01-01",
        "notes": "note",
    }


def test_save_and_load_roundtrip(tmp_path: Path):
    data = sample()
    path = save(tmp_path, data)
    assert path.name == f"{data['id']}.json"
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


def test_scan_ids_skips_invalid_and_labels(tmp_path: Path):
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps({"id": 1}))
    labels = tmp_path / "labels.json"
    labels.write_text("[]")
    bad = tmp_path / "bad.json"
    bad.write_text("{invalid json")

    ids = _scan_ids(tmp_path)
    assert ids == {1}


def test_save_accepts_dataclass(tmp_path: Path):
    req = Requirement(
        id=10,
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


def test_filename_for_sanitizes():
    assert filename_for(1) == "1.json"


def test_delete_updates_cache(tmp_path: Path):
    save(tmp_path, sample(1))
    delete(tmp_path, 1)
    save(tmp_path, sample(1))


def test_id_cache_scans_once_with_many_files(monkeypatch, tmp_path: Path):
    for i in range(100):
        (tmp_path / f"{i}.json").write_text(json.dumps({"id": i}))

    calls = {"n": 0}
    original = _scan_ids

    def spy(directory: Path) -> set[int]:
        calls["n"] += 1
        return original(directory)

    monkeypatch.setattr("app.core.store._scan_ids", spy)

    save(tmp_path, sample(100))
    save(tmp_path, sample(101))

    assert calls["n"] == 1


def test_mark_suspects_on_revision_change(tmp_path: Path):
    req1 = sample(1)
    req2 = sample(2)
    req2["derived_from"] = [{"source_id": 1, "source_revision": 1, "suspect": False}]

    save(tmp_path, req1)
    save(tmp_path, req2)

    # saving without revision change should not mark suspect
    save(tmp_path, req1)
    data, _ = load(tmp_path / filename_for(2))
    assert data["derived_from"][0]["suspect"] is False

    # change revision -> mark suspect
    req1["revision"] = 2
    save(tmp_path, req1)
    data, _ = load(tmp_path / filename_for(2))
    assert data["derived_from"][0]["suspect"] is True
