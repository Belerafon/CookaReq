import json
from http.client import HTTPConnection
from pathlib import Path

import pytest

from app.mcp.server import start_server, stop_server
from tests.mcp_utils import _wait_until_ready

pytestmark = pytest.mark.integration


_TEST_CONTEXT_LIMIT = 2048
_TEST_MODEL = "test-mcp"


@pytest.fixture
def documents_server(tmp_path: Path, free_tcp_port: int):
    port = free_tcp_port
    base_dir = tmp_path / "workspace"
    docs_dir = base_dir / "docs"
    guides = docs_dir / "guides"
    guides.mkdir(parents=True)
    (guides / "intro.txt").write_text("Welcome to the docs", encoding="utf-8")
    (docs_dir / "empty.txt").write_text("", encoding="utf-8")

    stop_server()
    start_server(
        port=port,
        base_path=str(base_dir),
        documents_path="docs",
        max_context_tokens=_TEST_CONTEXT_LIMIT,
        token_model=_TEST_MODEL,
    )
    _wait_until_ready(port)
    try:
        yield port, docs_dir
    finally:
        stop_server()


def _call_tool(port: int, name: str, arguments: dict | None = None) -> tuple[int, dict]:
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        body = json.dumps({"name": name, "arguments": arguments or {}})
        conn.request(
            "POST",
            "/mcp",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        payload_raw = resp.read().decode("utf-8") or "{}"
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            payload = {"raw": payload_raw}
        return resp.status, payload
    finally:
        conn.close()


def test_list_user_documents_returns_tree(documents_server):
    port, docs_dir = documents_server
    status, payload = _call_tool(port, "list_user_documents")
    assert status == 200
    assert payload["root"] == str((docs_dir).resolve())
    assert payload["max_context_tokens"] == _TEST_CONTEXT_LIMIT
    assert payload["max_read_bytes"] == 10 * 1024
    assert payload["max_read_kib"] == 10
    tree_text = payload["tree_text"]
    assert "guides" in tree_text
    assert "intro.txt" in tree_text


def test_read_user_document_returns_chunk(documents_server):
    port, _ = documents_server
    status, payload = _call_tool(
        port,
        "read_user_document",
        {"path": "guides/intro.txt", "start_line": 1, "max_bytes": 64},
    )
    assert status == 200
    assert payload["path"] == "guides/intro.txt"
    assert payload["content"].strip().endswith("Welcome to the docs")
    assert payload["truncated"] is False


def test_create_user_document_writes_file(documents_server):
    port, docs_dir = documents_server
    status, payload = _call_tool(
        port,
        "create_user_document",
        {
            "path": "notes/new.txt",
            "content": "Привет",
            "exist_ok": False,
            "encoding": "cp1251",
        },
    )
    assert status == 200
    assert payload["path"] == "notes/new.txt"
    assert payload["encoding"] == "cp1251"
    created_file = docs_dir / "notes" / "new.txt"
    assert created_file.exists()
    assert created_file.read_bytes() == "Привет".encode("cp1251")


def test_create_user_document_rejects_unknown_encoding(documents_server):
    port, _ = documents_server
    status, payload = _call_tool(
        port,
        "create_user_document",
        {
            "path": "notes/new.txt",
            "content": "text",
            "encoding": "unknown-encoding",
        },
    )
    assert status == 200
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert "Unknown encoding" in payload["error"]["message"]


def test_delete_user_document_removes_file(documents_server):
    port, docs_dir = documents_server
    target = docs_dir / "to-remove.txt"
    target.write_text("obsolete", encoding="utf-8")
    status, payload = _call_tool(
        port,
        "delete_user_document",
        {"path": "to-remove.txt"},
    )
    assert status == 200
    assert payload["deleted"] is True
    assert not target.exists()


def test_share_directory_is_readable(tmp_path: Path, free_tcp_port: int) -> None:
    port = free_tcp_port
    base_dir = tmp_path / "workspace"
    share_dir = base_dir / "share"
    share_dir.mkdir(parents=True)
    (share_dir / "guide.txt").write_text("Shared", encoding="utf-8")

    stop_server()
    start_server(
        port=port,
        base_path=str(base_dir),
        documents_path="share",
        max_context_tokens=_TEST_CONTEXT_LIMIT,
        token_model=_TEST_MODEL,
    )
    _wait_until_ready(port)
    try:
        status, payload = _call_tool(
            port,
            "read_user_document",
            {"path": "guide.txt", "max_bytes": 128},
        )
        assert status == 200
        assert payload["path"] == "guide.txt"
        assert "Shared" in payload["content"]
    finally:
        stop_server()


def test_tools_require_configured_root(tmp_path: Path, free_tcp_port: int):
    port = free_tcp_port
    stop_server()
    start_server(
        port=port,
        base_path=str(tmp_path),
        documents_path="",
        max_context_tokens=_TEST_CONTEXT_LIMIT,
        token_model=_TEST_MODEL,
    )
    _wait_until_ready(port)
    try:
        status, payload = _call_tool(port, "list_user_documents")
        assert status == 200
        assert payload["error"]["code"] == "NOT_FOUND"
    finally:
        stop_server()


def test_configured_read_limit_enforced(tmp_path: Path, free_tcp_port: int):
    port = free_tcp_port
    base_dir = tmp_path / "workspace"
    docs_dir = base_dir / "docs"
    docs_dir.mkdir(parents=True)
    target = docs_dir / "long.txt"
    target.write_text("A" * 4096, encoding="utf-8")

    stop_server()
    start_server(
        port=port,
        base_path=str(base_dir),
        documents_path="docs",
        max_context_tokens=_TEST_CONTEXT_LIMIT,
        token_model=_TEST_MODEL,
        documents_max_read_kb=1,
    )
    _wait_until_ready(port)
    try:
        status, payload = _call_tool(port, "read_user_document", {"path": "long.txt"})
        assert status == 200
        assert payload["bytes_consumed"] <= 1024
        assert payload["truncated"] is True

        status, payload = _call_tool(
            port,
            "read_user_document",
            {"path": "long.txt", "max_bytes": 2048},
        )
        assert status == 200
        assert payload["error"]["code"] == "VALIDATION_ERROR"
    finally:
        stop_server()
