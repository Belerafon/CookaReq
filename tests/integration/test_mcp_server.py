"""Tests for mcp server."""

import json
import logging

import pytest

from app.mcp.server import start_server, stop_server
from tests.mcp_utils import _request, _wait_until_ready

pytestmark = pytest.mark.integration


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


def test_stop_server_does_not_log_cancelled_error(caplog):
    port = 8127
    stop_server()
    start_server(port=port)
    try:
        _wait_until_ready(port)
        caplog.clear()
        with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
            stop_server()
    finally:
        stop_server()

    assert not any("CancelledError" in record.getMessage() for record in caplog.records)
