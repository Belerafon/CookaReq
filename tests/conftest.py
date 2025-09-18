"""Pytest fixtures and shared helpers."""

import os
import re
import sys
import time
import types
from pathlib import Path

# Ensure project root is on sys.path for imports
sys.path.append(str(Path(__file__).resolve().parents[1]))

import socket

import pytest

from app import i18n
from app.confirm import auto_confirm, set_confirm
from app.mcp.server import start_server, stop_server
from tests.llm_utils import make_openai_mock, require_real_llm_tests_flag
from tests.mcp_utils import _wait_until_ready


APP_NAME = "CookaReq"
LOCALE_DIR = Path(__file__).resolve().parents[1] / "app" / "locale"


@pytest.fixture(autouse=True)
def _reset_locale():
    """Ensure English translations are active for each test."""

    i18n.install(APP_NAME, str(LOCALE_DIR), ["en"])
    yield
    i18n.install(APP_NAME, str(LOCALE_DIR), ["en"])


@pytest.fixture(autouse=True)
def _mock_openrouter(monkeypatch, request):
    """Подменить OpenAI на мок, исключив реальные сетевые вызовы."""
    if request.node.get_closest_marker("real_llm"):
        require_real_llm_tests_flag()
        return
    monkeypatch.setattr("openai.OpenAI", make_openai_mock({}))


@pytest.fixture(autouse=True)
def _auto_confirm():
    set_confirm(auto_confirm)
    yield


@pytest.fixture(autouse=True)
def _isolate_wx_config(monkeypatch, tmp_path_factory):
    """Persist wx.Config data under a per-test directory."""

    try:
        import wx  # noqa: WPS433 - optional dependency in tests
    except ModuleNotFoundError:
        # Tests that stub ``wx`` can still run without the real library.
        yield
        return

    root = tmp_path_factory.mktemp("wx-config")
    created_paths: dict[str, Path] = {}

    def _normalise_app_name(app_name: object | None) -> str:
        if app_name is None:
            return "wx"
        text = str(app_name)
        if not text:
            return "wx"
        return re.sub(r"[^A-Za-z0-9_.-]", "_", text)

    def _get_config_path(app_name: object | None) -> Path:
        key = _normalise_app_name(app_name)
        path = created_paths.get(key)
        if path is None:
            path = root / f"{key}.ini"
            created_paths[key] = path
        return path

    def _make_config(*args, **kwargs):
        params = dict(kwargs)
        app_name = params.get("appName")
        if app_name is None and args:
            app_name = args[0]
        params.setdefault("localFilename", str(_get_config_path(app_name)))
        return wx.FileConfig(*args, **params)

    monkeypatch.setattr(wx, "Config", _make_config)
    try:
        yield
    finally:
        for path in created_paths.values():
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

def pytest_collection_modifyitems(config, items):
    """Automatically add markers based on module-level requirements flags."""

    for item in items:
        module = getattr(item, "module", None)
        if module is None:
            continue
        if getattr(module, "REQUIRES_REAL_LLM", False) and not item.get_closest_marker(
            "real_llm"
        ):
            item.add_marker("real_llm")
        if getattr(module, "REQUIRES_GUI", False) and not item.get_closest_marker("gui"):
            item.add_marker("gui")


def _start_virtual_display_if_needed():
    """Ensure GUI tests have access to a display, falling back to Xvfb when possible."""

    if os.name == "nt" or os.environ.get("DISPLAY"):
        return None

    try:
        from pyvirtualdisplay import Display
    except Exception as exc:  # pragma: no cover - informative skip
        pytest.skip(
            "GUI tests require an X server. Install pytest-xvfb (pip install pytest-xvfb) "
            "so it can start Xvfb automatically, or execute pytest under xvfb-run."
            f" PyVirtualDisplay could not be imported: {exc}",
        )

    display = Display(visible=False, size=(1280, 800))
    try:
        display.start()
    except Exception as exc:  # pragma: no cover - informative skip
        pytest.skip(
            "Could not start a virtual display for GUI tests. Ensure the Xvfb binary is "
            "available and let pytest-xvfb handle startup, or wrap the run in xvfb-run."
            f" Original error: {exc!r}",
        )
    return display


@pytest.fixture(scope="session")
def wx_app():
    """Provide wx.App instance, starting a virtual display when no DISPLAY is present."""

    display = _start_virtual_display_if_needed()
    wx = pytest.importorskip("wx")
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - informative failure
        pytest.fail(
            "wx.App() failed to initialise. Ensure the pytest-xvfb plugin is active so "
            "it can launch Xvfb automatically, or run the suite via xvfb-run in headless "
            f"environments. Original error: {exc!r}",
        )

    def _safe_yield(self=None, *args, **kwargs):
        target = self if self is not None else app
        if target is None:
            return False
        target.ProcessPendingEvents()
        return True

    app.Yield = types.MethodType(_safe_yield, app)

    def _module_safe_yield(*args, **kwargs):
        return _safe_yield(app, *args, **kwargs)

    wx.Yield = _module_safe_yield
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
    """Run MCP server on a free port for the duration of tests."""
    port = _get_free_port()
    stop_server()
    start_server(port=port, base_path="")
    _wait_until_ready(port)
    yield port
    stop_server()


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    """Store test session start time for summary reporting."""
    session.config._start_time = time.time()


@pytest.hookimpl(trylast=True)
def pytest_terminal_summary(terminalreporter, exitstatus):
    """Print concise summary including duration at end of test run."""
    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    skipped = len(terminalreporter.stats.get("skipped", []))
    duration = time.time() - terminalreporter.config._start_time
    terminalreporter.write_sep(
        "=",
        f"{passed} passed, {failed} failed, {skipped} skipped in {duration:.2f}s",
    )
