import time
import time
from http.client import HTTPConnection

from app.mcp.server import start_server, stop_server


def _request(port, headers=None):
    conn = HTTPConnection("127.0.0.1", port)
    conn.request("GET", "/health", headers=headers or {})
    resp = conn.getresponse()
    body = resp.read().decode()
    conn.close()
    return resp.status, body


def test_authorization_header_rejected_without_valid_token():
    port = 8123
    stop_server()  # ensure clean state
    start_server(port=port, token="secret")
    try:
        # wait for server to be ready
        for _ in range(50):
            try:
                _request(port, {"Authorization": "Bearer wrong"})
                break
            except ConnectionRefusedError:
                time.sleep(0.1)
        status, body = _request(port, {"Authorization": "Bearer wrong"})
        assert status == 401
        assert "UNAUTHORIZED" in body
    finally:
        stop_server()
