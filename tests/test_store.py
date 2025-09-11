from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.core.store import ConflictError, load, save, filename_for


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
