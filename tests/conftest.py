"""Pytest fixtures and shared helpers."""

import os
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest
from app.confirm import set_confirm, auto_confirm
from app.mcp.server import start_server, stop_server, app as mcp_app
from tests.mcp_utils import _wait_until_ready
import socket


@pytest.fixture(autouse=True)
def _mock_openrouter(monkeypatch):
    """Подменить OpenAI на мок, исключив реальные сетевые вызовы."""
    from tests.llm_utils import make_openai_mock

    monkeypatch.setattr("openai.OpenAI", make_openai_mock({}))


@pytest.fixture(autouse=True)
def _auto_confirm():
    set_confirm(auto_confirm)
    yield


@pytest.fixture(scope="session")
def wx_app():
    display = None
    if os.name != "nt" and not os.environ.get("DISPLAY"):
        try:
            from pyvirtualdisplay import Display
        except Exception:
            Display = None
        if Display is not None:
            display = Display(visible=False, size=(1280, 800))
            display.start()
    wx = pytest.importorskip("wx")
    app = wx.App()
    yield app
    app.Destroy()
    if display is not None:
        display.stop()


def _get_free_port() -> int:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


@pytest.fixture(scope="module")
def mcp_server():
    port = _get_free_port()
    stop_server()
    start_server(port=port, base_path="")
    _wait_until_ready(port)
    yield port
    stop_server()


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    session.config._start_time = time.time()


@pytest.hookimpl(trylast=True)
def pytest_terminal_summary(terminalreporter, exitstatus):
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    skipped = len(terminalreporter.stats.get("skipped", []))
    duration = time.time() - terminalreporter.config._start_time
    terminalreporter.write_sep(
        "=", f"{passed} passed, {failed} failed, {skipped} skipped in {duration:.2f}s"
    )
