"""Tests for mcp http tools."""

from __future__ import annotations

import json
from http.client import HTTPConnection
from pathlib import Path

import pytest

from app.core import store
from app.mcp.server import start_server, stop_server
from tests.mcp_utils import _wait_until_ready

pytestmark = pytest.mark.integration


def _sample(req_id: int, title: str, labels: list[str] | None = None) -> dict:
    return {
        "id": req_id,
        "title": title,
        "statement": "Statement",
        "type": "requirement",
        "status": "draft",
        "owner": "user",
        "priority": "medium",
        "source": "spec",
        "verification": "analysis",
        "labels": labels or [],
        "revision": 1,
    }


def _prepare(tmp_path: Path) -> None:
    store.save(tmp_path, _sample(1, "A"))
    store.save(tmp_path, _sample(2, "B"))


def _call_tool(port: int, name: str, arguments: dict | None = None):
    conn = HTTPConnection("127.0.0.1", port)
    payload = json.dumps({"name": name, "arguments": arguments or {}})
    conn.request(
        "POST",
        "/mcp",
        body=payload,
        headers={"Content-Type": "application/json"},
    )
    resp = conn.getresponse()
    body = json.loads(resp.read().decode())
    conn.close()
    return resp.status, body


def test_list_requirements_via_http(tmp_path: Path) -> None:
    _prepare(tmp_path)
    port = 8127
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        status, body = _call_tool(port, "list_requirements")
        assert status == 200
        ids = {item["id"] for item in body["items"]}
        assert ids == {1, 2}
    finally:
        stop_server()


def test_get_requirement_via_http(tmp_path: Path) -> None:
    _prepare(tmp_path)
    port = 8128
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        status, body = _call_tool(port, "get_requirement", {"req_id": 1})
        assert status == 200
        assert body["id"] == 1
    finally:
        stop_server()


def test_search_requirements_via_http(tmp_path: Path) -> None:
    _prepare(tmp_path)
    port = 8129
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        status, body = _call_tool(port, "search_requirements", {"query": "B"})
        assert status == 200
        ids = {item["id"] for item in body["items"]}
        assert ids == {2}
    finally:
        stop_server()


def test_list_requirements_filter_labels_via_http(tmp_path: Path) -> None:
    store.save(tmp_path, _sample(1, "A", ["ui"]))
    store.save(tmp_path, _sample(2, "B", ["backend"]))
    port = 8134
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        status, body = _call_tool(port, "list_requirements", {"labels": ["ui"]})
        assert status == 200
        ids = {item["id"] for item in body["items"]}
        assert ids == {1}
    finally:
        stop_server()


def test_create_requirement_via_http(tmp_path: Path) -> None:
    port = 8130
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        status, body = _call_tool(port, "create_requirement", {"data": _sample(3, "C")})
        assert status == 200
        status, body = _call_tool(port, "list_requirements")
        ids = {item["id"] for item in body["items"]}
        assert ids == {3}
    finally:
        stop_server()


def test_patch_requirement_via_http(tmp_path: Path) -> None:
    _prepare(tmp_path)
    port = 8131
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        status, body = _call_tool(
            port,
            "patch_requirement",
            {
                "req_id": 1,
                "patch": [{"op": "replace", "path": "/title", "value": "A2"}],
                "rev": 1,
            },
        )
        assert status == 200
        assert body["title"] == "A2"
        assert body["revision"] == 2
    finally:
        stop_server()


def test_delete_requirement_via_http(tmp_path: Path) -> None:
    _prepare(tmp_path)
    port = 8132
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        status, body = _call_tool(port, "delete_requirement", {"req_id": 1, "rev": 1})
        assert status == 200
        status, body = _call_tool(port, "list_requirements")
        ids = {item["id"] for item in body["items"]}
        assert ids == {2}
    finally:
        stop_server()


def test_link_requirements_via_http(tmp_path: Path) -> None:
    _prepare(tmp_path)
    port = 8133
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        status, body = _call_tool(
            port,
            "link_requirements",
            {"source_id": 1, "derived_id": 2, "link_type": "derived_from", "rev": 1},
        )
        assert status == 200
        assert body["revision"] == 2
        assert body["derived_from"] == [
            {"source_id": 1, "source_revision": 1, "suspect": False},
        ]
    finally:
        stop_server()
