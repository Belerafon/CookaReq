"""Tests for mcp logging."""

import json
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app.mcp.server import app as mcp_app
from app.mcp.server import start_server, stop_server
from tests.mcp_utils import _request, _wait_until_ready

pytestmark = pytest.mark.integration


def test_request_logged_and_token_masked():
    port = 8124
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        stop_server()
        start_server(
            port=port,
            base_path=tmp,
            token="secret",
            log_dir=tmp_path,
            max_context_tokens=8192,
            token_model="test-mcp",
        )
        try:
            _wait_until_ready(port, {"Authorization": "Bearer secret"})
            status, _ = _request(port, {"Authorization": "Bearer secret"})
            assert status == 200
            assert Path(mcp_app.state.log_dir) == tmp_path
        finally:
            stop_server()

        log_path = tmp_path / "server.log"
        jsonl_path = tmp_path / "server.jsonl"
        assert log_path.exists()
        assert jsonl_path.exists()

        with log_path.open(encoding="utf-8") as fh:
            content = fh.read()
        assert "GET /health" in content
        assert "secret" not in content

        with jsonl_path.open(encoding="utf-8") as fh:
            line = fh.readline()
        entry = json.loads(line)
        assert entry["status"] == 200
        assert entry.get("path") == "/health"
        assert "request_id" in entry and entry["request_id"]
        assert entry.get("duration_ms") is not None
        headers = entry["headers"]
        auth = headers.get("Authorization") or headers.get("authorization")
        assert auth == "[REDACTED]"
        assert "secret" not in json.dumps(entry)


def test_tool_request_logs_share_request_id(tmp_path: Path):
    port = 8128
    stop_server()
    start_server(
        port=port,
        base_path=str(tmp_path),
        log_dir=tmp_path,
        max_context_tokens=8192,
        token_model="test-mcp",
    )
    try:
        _wait_until_ready(port)
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(
                "POST",
                "/mcp",
                body=json.dumps({"name": "list_requirements", "arguments": {"per_page": 1}}),
                headers={"Content-Type": "application/json"},
            )
            resp = conn.getresponse()
            assert resp.status == 200
            resp.read()
        finally:
            conn.close()
    finally:
        stop_server()

    log_path = tmp_path / "server.jsonl"
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().splitlines()]
    request_entries = [entry for entry in entries if entry.get("path") == "/mcp"]
    assert request_entries, "expected request log for /mcp"
    tool_entries = [entry for entry in entries if entry.get("tool") == "list_requirements"]
    assert tool_entries, "expected tool event for list_requirements"
    req_id = request_entries[-1]["request_id"]
    assert req_id
    assert all(item.get("request_id") == req_id for item in tool_entries)
    for item in tool_entries:
        assert item.get("outcome") == "ok"
        assert item.get("arguments") == {"per_page": 1}
