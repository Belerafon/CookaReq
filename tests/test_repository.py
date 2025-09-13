from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.core.repository import FileRequirementRepository
from app.core.store import ConflictError


def sample(req_id: int = 1) -> dict:
    return {
        "id": req_id,
        "title": f"Title {req_id}",
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
        "labels": [],
    }


def test_save_get_delete_roundtrip(tmp_path: Path):
    repo = FileRequirementRepository()
    data = sample(1)
    path = repo.save(tmp_path, data)
    assert path.exists()
    req = repo.get(tmp_path, 1)
    assert req.title == data["title"]
    repo.delete(tmp_path, 1)
    assert not path.exists()
    with pytest.raises(FileNotFoundError):
        repo.get(tmp_path, 1)


def test_load_all_and_search(tmp_path: Path):
    repo = FileRequirementRepository()
    r1 = sample(1)
    r1["title"] = "Alpha"
    r1["labels"] = ["x"]
    r2 = sample(2)
    r2["title"] = "Beta"
    r2["labels"] = ["y"]
    repo.save(tmp_path, r1)
    repo.save(tmp_path, r2)

    all_reqs = repo.load_all(tmp_path)
    assert [r.id for r in all_reqs] == [1, 2]

    res = repo.search(tmp_path, query="Beta")
    assert [r.id for r in res] == [2]

    res = repo.search(tmp_path, labels=["x"])
    assert [r.id for r in res] == [1]


def test_get_missing_file(tmp_path: Path):
    repo = FileRequirementRepository()
    with pytest.raises(FileNotFoundError):
        repo.get(tmp_path, 1)


def test_save_conflict_detection(tmp_path: Path):
    repo = FileRequirementRepository()
    data = sample(1)
    path = repo.save(tmp_path, data)
    loaded, mtime = repo.load(tmp_path, 1)
    time.sleep(1)
    path.write_text(json.dumps(loaded))
    with pytest.raises(ConflictError):
        repo.save(tmp_path, data, mtime=mtime)


def test_save_updates_modified_at(tmp_path: Path):
    repo = FileRequirementRepository()
    data = sample(1)
    data["modified_at"] = "2020-01-01 00:00:00"
    repo.save(tmp_path, data)
    saved = repo.get(tmp_path, 1)
    assert saved.modified_at != ""
    assert saved.modified_at != data["modified_at"]


def test_save_respects_explicit_modified_at(tmp_path: Path):
    repo = FileRequirementRepository()
    data = sample(1)
    ts = "2022-02-03 04:05:06"
    repo.save(tmp_path, data, modified_at=ts)
    saved = repo.get(tmp_path, 1)
    assert saved.modified_at == ts
