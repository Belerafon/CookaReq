"""Tests for mcp server."""

import json
import logging
from pathlib import Path

import pytest

from app.mcp.server import app as mcp_app
from app.mcp.server import start_server, stop_server
from app.log import get_log_directory
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


def test_default_log_directory_used_when_base_path_missing():
    port = 8129
    stop_server()
    start_server(port=port, base_path="")
    try:
        _wait_until_ready(port)
        log_dir = Path(mcp_app.state.log_dir)
        expected = get_log_directory() / "mcp"
        assert log_dir == expected
    finally:
        stop_server()


def test_base_path_does_not_override_log_directory(tmp_path: Path):
    port = 8130
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        log_dir = Path(mcp_app.state.log_dir)
        expected = get_log_directory() / "mcp"
        assert log_dir == expected
        assert log_dir != tmp_path
    finally:
        stop_server()
