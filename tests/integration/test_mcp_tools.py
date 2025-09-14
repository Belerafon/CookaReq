"""Tests for mcp tools."""

from pathlib import Path

from app.core import store
from app.mcp.tools_read import list_requirements, get_requirement, search_requirements
from app.mcp.utils import ErrorCode


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

    result = list_requirements(tmp_path, labels=["ui"], page=2, per_page=1)
    assert result["total"] == 2
    assert [item["id"] for item in result["items"]] == [3]


def test_list_requirements_errors(tmp_path: Path, monkeypatch) -> None:
    # directory missing
    def not_found(_):  # noqa: ANN001
        raise FileNotFoundError

    monkeypatch.setattr("app.core.requirements.load_all", not_found)
    err = list_requirements(tmp_path / "missing")
    assert err["error"]["code"] == ErrorCode.NOT_FOUND

    # internal error
    def boom(_):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr("app.core.requirements.load_all", boom)
    err = list_requirements(tmp_path)
    assert err["error"]["code"] == ErrorCode.INTERNAL


def test_get_requirement(tmp_path: Path) -> None:
    _prepare(tmp_path)
    item = get_requirement(tmp_path, 2)
    assert item["id"] == 2
    assert item["title"] == "Store data"


def test_get_requirement_errors(tmp_path: Path, monkeypatch) -> None:
    _prepare(tmp_path)
    err = get_requirement(tmp_path, 99)
    assert err["error"]["code"] == ErrorCode.NOT_FOUND

    def boom(*args, **kwargs):  # noqa: ANN001, ANN002
        raise RuntimeError("boom")

    monkeypatch.setattr("app.core.requirements.load_requirement", boom)
    err = get_requirement(tmp_path, 1)
    assert err["error"]["code"] == ErrorCode.INTERNAL


def test_search_requirements(tmp_path: Path) -> None:
    _prepare(tmp_path)
    result = search_requirements(tmp_path, query="login")
    assert [item["id"] for item in result["items"]] == [1]

    result = search_requirements(tmp_path, labels=["ui"], per_page=1, page=2)
    assert [item["id"] for item in result["items"]] == [3]

    result = search_requirements(tmp_path, status="approved")
    assert [item["id"] for item in result["items"]] == [2]


def test_search_requirements_errors(tmp_path: Path, monkeypatch) -> None:
    def not_found(_):  # noqa: ANN001
        raise FileNotFoundError

    monkeypatch.setattr("app.core.requirements.load_all", not_found)
    err = search_requirements(tmp_path / "nope", query="login")
    assert err["error"]["code"] == ErrorCode.NOT_FOUND

    def boom(_):  # noqa: ANN001
        raise RuntimeError("boom")

    monkeypatch.setattr("app.core.requirements.load_all", boom)
    err = search_requirements(tmp_path)
    assert err["error"]["code"] == ErrorCode.INTERNAL
