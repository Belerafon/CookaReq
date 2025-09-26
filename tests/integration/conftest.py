"""Integration-test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.mcp.server import start_server, stop_server
from tests.mcp_utils import _wait_until_ready


@pytest.fixture
def mcp_server(tmp_path_factory: pytest.TempPathFactory, free_tcp_port: int) -> int:
    """Start the MCP server on a temporary port for the duration of a test."""

    port = free_tcp_port
    base_dir: Path = tmp_path_factory.mktemp("mcp-server")

    stop_server()
    start_server(port=port, base_path=str(base_dir))
    _wait_until_ready(port)

    try:
        yield port
    finally:
        stop_server()
