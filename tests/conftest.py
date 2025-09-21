"""Pytest fixtures and shared helpers."""

import os
import re
import sys
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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
TESTS_ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class SuiteConfig:
    """Definition of a logical pytest suite."""

    mark_expression: str | None
    description: str
    note: str | None = None


SUITE_DEFINITIONS: dict[str, SuiteConfig] = {
    "core": SuiteConfig(
        "core",
        "Fast local checks (unit tests, smoke tests, isolated helpers).",
    ),
    "service": SuiteConfig(
        "core or service",
        "Integration scenarios for the MCP/CLI stack; runs the core suite first.",
    ),
    "gui-smoke": SuiteConfig(
        "gui_smoke",
        "Minimal GUI subset that opens the main windows without exhaustive coverage.",
    ),
    "gui": SuiteConfig(
        "gui_full",
        "Complete GUI regression matrix (slow, uses real wx widgets).",
    ),
    "quality": SuiteConfig(
        "quality",
        "Static analysis wrappers (ruff, pydocstyle, vulture, translations).",
    ),
    "all": SuiteConfig(
        None,
        "Entire pytest suite with no marker filtering.",
    ),
    "real-llm": SuiteConfig(
        "real_llm",
        "Live OpenRouter integration checks (requires COOKAREQ_RUN_REAL_LLM_TESTS=1)",
        note="Set OPEN_ROUTER and COOKAREQ_RUN_REAL_LLM_TESTS=1 before running.",
    ),
}


_PATH_MARKERS: tuple[tuple[Path, tuple[str, ...]], ...] = tuple(
    (path.resolve(), markers)
    for path, markers in (
        (TESTS_ROOT / "unit", ("unit", "core")),
        (TESTS_ROOT / "smoke", ("smoke", "core")),
        (TESTS_ROOT / "integration", ("integration", "service")),
        (TESTS_ROOT / "gui", ("gui", "gui_full")),
        (TESTS_ROOT / "slow", ("slow", "quality")),
    )
)

_FILE_MARKERS: dict[Path, tuple[str, ...]] = {
    (TESTS_ROOT / "test_util_cancellation.py").resolve(): ("core",),
}


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register custom suite options so the CLI documents available groups."""

    group = parser.getgroup("CookaReq test suites")
    group.addoption(
        "--suite",
        action="store",
        default=None,
        choices=list(SUITE_DEFINITIONS),
        help="Run a predefined CookaReq suite (see --list-suites).",
    )
    group.addoption(
        "--list-suites",
        action="store_true",
        help="List the predefined CookaReq suites and exit.",
    )


def pytest_cmdline_main(config: pytest.Config) -> int | None:
    """Handle ``--list-suites`` before tests start running."""

    if not config.getoption("--list-suites"):
        return None

    from _pytest.config import create_terminal_writer

    terminal_writer = create_terminal_writer(config)
    terminal_writer.line("Available CookaReq test suites:\n")
    name_width = max(len(name) for name in SUITE_DEFINITIONS)
    expr_width = max(len(cfg.mark_expression or "<all>") for cfg in SUITE_DEFINITIONS.values())

    for name, cfg in SUITE_DEFINITIONS.items():
        expression = cfg.mark_expression or "<all>"
        terminal_writer.line(f"  {name.ljust(name_width)}  {expression.ljust(expr_width)}  {cfg.description}")
        if cfg.note:
            terminal_writer.line(f"      note: {cfg.note}")

    return 0


def pytest_configure(config: pytest.Config) -> None:
    """Apply suite marker expressions unless the user overrode ``-m`` manually."""

    suite_name = config.getoption("--suite")
    if not suite_name:
        return
    if config.option.markexpr:
        # Respect an explicit ``-m`` expression from the command line.
        return

    suite_config = SUITE_DEFINITIONS[suite_name]
    if suite_config.mark_expression is None:
        config.option.markexpr = None
    else:
        config.option.markexpr = suite_config.mark_expression


def _iter_path_markers(path: Path) -> Iterable[str]:
    for root, markers in _PATH_MARKERS:
        try:
            path.relative_to(root)
        except ValueError:
            continue
        yield from markers


def _iter_file_markers(path: Path) -> Iterable[str]:
    markers = _FILE_MARKERS.get(path)
    if markers:
        yield from markers


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
    """Automatically add markers based on module flags and file locations."""

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

    for item in items:
        path = Path(str(item.fspath)).resolve()
        for marker in _iter_path_markers(path):
            if not item.get_closest_marker(marker):
                item.add_marker(marker)
        for marker in _iter_file_markers(path):
            if not item.get_closest_marker(marker):
                item.add_marker(marker)

        if item.get_closest_marker("gui") and not item.get_closest_marker("gui_full"):
            item.add_marker("gui_full")
        if item.get_closest_marker("gui_smoke") and not item.get_closest_marker("gui_full"):
            item.add_marker("gui_full")
        if item.get_closest_marker("slow") and not item.get_closest_marker("quality"):
            item.add_marker("quality")
        if item.get_closest_marker("smoke") and not item.get_closest_marker("core"):
            item.add_marker("core")


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
