from pathlib import Path

from app.core import store
from app.mcp.tools_read import list_requirements, get_requirement, search_requirements


def _sample(req_id: int, title: str, status: str, labels: list[str]) -> dict:
    return {
        "id": req_id,
        "title": title,
        "statement": "Statement",
        "type": "requirement",
        "status": status,
        "owner": "user",
        "priority": "medium",
        "source": "spec",
        "verification": "analysis",
        "labels": labels,
        "revision": 1,
    }


def _prepare(tmp_path: Path) -> None:
    store.save(tmp_path, _sample(1, "Login form", "draft", ["ui", "auth"]))
    store.save(tmp_path, _sample(2, "Store data", "approved", ["backend"]))
    store.save(tmp_path, _sample(3, "Export report", "draft", ["ui"]))


def test_list_requirements_filters_and_paginates(tmp_path: Path) -> None:
    _prepare(tmp_path)
    result = list_requirements(tmp_path, status="draft")
    assert result["total"] == 2
    ids = {item["id"] for item in result["items"]}
    assert ids == {1, 3}

    result = list_requirements(tmp_path, tags=["ui"], page=2, per_page=1)
    assert result["total"] == 2
    assert [item["id"] for item in result["items"]] == [3]


def test_get_requirement(tmp_path: Path) -> None:
    _prepare(tmp_path)
    item = get_requirement(tmp_path, 2)
    assert item["id"] == 2
    assert item["title"] == "Store data"


def test_search_requirements(tmp_path: Path) -> None:
    _prepare(tmp_path)
    result = search_requirements(tmp_path, query="login")
    assert [item["id"] for item in result["items"]] == [1]

    result = search_requirements(tmp_path, tags=["ui"], per_page=1, page=2)
    assert [item["id"] for item in result["items"]] == [3]

    result = search_requirements(tmp_path, status="approved")
    assert [item["id"] for item in result["items"]] == [2]
