"""Tests for mcp server."""

import json
import logging
import json
import logging
from pathlib import Path

import pytest

from app.mcp.server import app as mcp_app
from app.mcp.server import start_server, stop_server
from app.log import get_log_directory
from tests.mcp_utils import _request, _wait_until_ready

_TEST_CONTEXT_LIMIT = 8192
_TEST_MODEL = "test-mcp"

pytestmark = pytest.mark.integration


def test_background_server_health_endpoint():
    port = 8125
    stop_server()
    start_server(port=port, max_context_tokens=_TEST_CONTEXT_LIMIT, token_model=_TEST_MODEL)
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
    start_server(
        port=port,
        token="secret",
        max_context_tokens=_TEST_CONTEXT_LIMIT,
        token_model=_TEST_MODEL,
    )
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
    start_server(port=port, max_context_tokens=_TEST_CONTEXT_LIMIT, token_model=_TEST_MODEL)
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
    start_server(
        port=port,
        base_path="",
        max_context_tokens=_TEST_CONTEXT_LIMIT,
        token_model=_TEST_MODEL,
    )
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
    start_server(
        port=port,
        base_path=str(tmp_path),
        max_context_tokens=_TEST_CONTEXT_LIMIT,
        token_model=_TEST_MODEL,
    )
    try:
        _wait_until_ready(port)
        log_dir = Path(mcp_app.state.log_dir)
        expected = get_log_directory() / "mcp"
        assert log_dir == expected
        assert log_dir != tmp_path
    finally:
        stop_server()


def test_documents_root_defaults_to_share(tmp_path: Path):
    port = 8131
    stop_server()
    start_server(
        port=port,
        base_path=str(tmp_path),
        max_context_tokens=_TEST_CONTEXT_LIMIT,
        token_model=_TEST_MODEL,
    )
    try:
        _wait_until_ready(port)
        assert Path(mcp_app.state.documents_root) == (tmp_path / "share").resolve()
        assert mcp_app.state.documents_max_read_bytes == 10 * 1024
    finally:
        stop_server()


def test_custom_documents_read_limit_in_state(tmp_path: Path):
    port = 8132
    stop_server()
    start_server(
        port=port,
        base_path=str(tmp_path),
        documents_path="docs",
        max_context_tokens=_TEST_CONTEXT_LIMIT,
        token_model=_TEST_MODEL,
        documents_max_read_kb=64,
    )
    try:
        _wait_until_ready(port)
        assert mcp_app.state.documents_max_read_bytes == 64 * 1024
        service = mcp_app.state.documents_service
        assert service is not None
        assert service.max_read_bytes == 64 * 1024
    finally:
        stop_server()
