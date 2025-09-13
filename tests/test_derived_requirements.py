"""Tests for derived requirements."""

from __future__ import annotations
from pathlib import Path

from app.core.store import save, load, filename_for
from app.core.model import Requirement, requirement_from_dict
from app.core.search import search



def _base(req_id: int) -> dict:
    return {
        "id": req_id,
        "title": f"R{req_id}",
        "statement": "S",
        "type": "requirement",
        "status": "draft",
        "owner": "o",
        "priority": "medium",
        "source": "src",
        "verification": "analysis",
        "revision": 1,
    }


def test_store_roundtrip_derived_fields(tmp_path: Path) -> None:
    src = _base(1)
    derived = _base(2)
    derived["derived_from"] = [{"source_id": 1, "source_revision": 1, "suspect": False}]
    derived["derivation"] = {
        "rationale": "calc",
        "assumptions": ["a1", "a2"],
        "method": "m",
        "margin": "10%",
    }

    save(tmp_path, src)
    save(tmp_path, derived)

    data, _ = load(tmp_path / filename_for(2))
    req = requirement_from_dict(data)

    assert req.derived_from[0].source_id == 1
    assert req.derived_from[0].suspect is False
    assert req.derivation is not None
    assert req.derivation.method == "m"
    assert req.derivation.assumptions == ["a1", "a2"]


def test_suspect_mark_on_source_revision_change(tmp_path: Path) -> None:
    src = _base(1)
    derived = _base(2)
    derived["derived_from"] = [{"source_id": 1, "source_revision": 1, "suspect": False}]

    save(tmp_path, src)
    save(tmp_path, derived)

    src["revision"] = 2
    save(tmp_path, src)

    data, _ = load(tmp_path / filename_for(2))
    assert data["derived_from"][0]["suspect"] is True


def test_search_filters_is_and_has_derived() -> None:
    req1 = requirement_from_dict(_base(1))
    derived_data = _base(2)
    derived_data["derived_from"] = [{"source_id": 1, "source_revision": 1, "suspect": False}]
    req2 = requirement_from_dict(derived_data)
    reqs: list[Requirement] = [req1, req2]

    assert [r.id for r in search(reqs, is_derived=True)] == [2]
    assert [r.id for r in search(reqs, has_derived=True)] == [1]
