"""Tests for mcp server."""

import json

from app.mcp.server import start_server, stop_server
from tests.mcp_utils import _request, _wait_until_ready


def test_background_server_health_endpoint():
    port = 8125
    stop_server()
    start_server(port=port)
    try:
        _wait_until_ready(port)
        status, body = _request(port)
        assert status == 200
        assert json.loads(body) == {"status": "ok"}
    finally:
        stop_server()


def test_missing_token_results_in_unauthorized():
    port = 8126
    stop_server()
    start_server(port=port, token="secret")
    try:
        _wait_until_ready(port)
        status, body = _request(port)
        assert status == 401
        assert "UNAUTHORIZED" in body
    finally:
        stop_server()
