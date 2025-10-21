"""Integration-test fixtures."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.log import LOG_DIR_ENV, configure_logging
from app.mcp.server import start_server, stop_server
from tests.mcp_utils import _wait_until_ready


@pytest.fixture(scope="session")
def real_llm_log_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Configure application logging to capture real LLM traffic to files."""

    log_dir = tmp_path_factory.mktemp("real-llm-logs")
    os.environ[LOG_DIR_ENV] = str(log_dir)
    configure_logging(log_dir=log_dir)
    return log_dir


@pytest.fixture
def mcp_server(tmp_path_factory: pytest.TempPathFactory, free_tcp_port: int) -> int:
    """Start the MCP server on a temporary port for the duration of a test."""

    port = free_tcp_port
    base_dir: Path = tmp_path_factory.mktemp("mcp-server")

    stop_server()
    start_server(
        port=port,
        base_path=str(base_dir),
        max_context_tokens=8192,
        token_model="test-mcp",
    )
    _wait_until_ready(port)

    try:
        yield port
    finally:
        stop_server()
