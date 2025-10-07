"""Tests for mcp auth."""

import pytest

from app.mcp.server import start_server, stop_server
from tests.mcp_utils import _request, _wait_until_ready

_TEST_CONTEXT_LIMIT = 8192
_TEST_MODEL = "test-mcp"

pytestmark = pytest.mark.integration


def test_authorization_header_rejected_without_valid_token():
    port = 8123
    stop_server()  # ensure clean state
    start_server(
        port=port,
        token="secret",
        max_context_tokens=_TEST_CONTEXT_LIMIT,
        token_model=_TEST_MODEL,
    )
    try:
        _wait_until_ready(port, {"Authorization": "Bearer wrong"})
        status, body = _request(port, {"Authorization": "Bearer wrong"})
        assert status == 401
        assert "UNAUTHORIZED" in body
    finally:
        stop_server()
