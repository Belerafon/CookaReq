"""Tests for mcp logging."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from app.mcp.server import start_server, stop_server
from tests.mcp_utils import _request, _wait_until_ready

pytestmark = pytest.mark.integration


def test_request_logged_and_token_masked():
    port = 8124
    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        stop_server()
        start_server(port=port, base_path=tmp, token="secret")
        try:
            _wait_until_ready(port, {"Authorization": "Bearer secret"})
            status, _ = _request(port, {"Authorization": "Bearer secret"})
            assert status == 200
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
        headers = entry["headers"]
        auth = headers.get("Authorization") or headers.get("authorization")
        assert auth == "[REDACTED]"
        assert "secret" not in json.dumps(entry)
