import json
import os
import time
from http.client import HTTPConnection
from tempfile import TemporaryDirectory

from app.mcp.server import start_server, stop_server


def _request(port, headers=None):
    conn = HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/health", headers=headers or {})
    resp = conn.getresponse()
    resp.read()
    conn.close()
    return resp.status


def test_request_logged_and_token_masked():
    port = 8124
    with TemporaryDirectory() as tmp:
        stop_server()
        start_server(port=port, base_path=tmp, token="secret")
        try:
            # wait for server to be ready
            for _ in range(50):
                try:
                    _request(port, {"Authorization": "Bearer secret"})
                    break
                except ConnectionRefusedError:
                    time.sleep(0.1)
            status = _request(port, {"Authorization": "Bearer secret"})
            assert status == 200
        finally:
            stop_server()

        log_path = os.path.join(tmp, "server.log")
        jsonl_path = os.path.join(tmp, "server.jsonl")
        assert os.path.exists(log_path)
        assert os.path.exists(jsonl_path)

        with open(log_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        assert "GET /health" in content
        assert "secret" not in content

        with open(jsonl_path, "r", encoding="utf-8") as fh:
            line = fh.readline()
        entry = json.loads(line)
        headers = entry["headers"]
        auth = headers.get("Authorization") or headers.get("authorization")
        assert auth == "***"
        assert "secret" not in json.dumps(entry)
