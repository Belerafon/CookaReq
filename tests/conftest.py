"""Pytest configuration for the CookaReq test suite."""

from __future__ import annotations

import contextlib
from types import MethodType, ModuleType
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import pytest

from tests.env_utils import load_dotenv_variables

# Load the nearest .env file once so integration tests that rely on external
# services (for example OpenRouter) automatically receive credentials without
# requiring ``source .env`` beforehand.
load_dotenv_variables(search_from=Path(__file__).resolve())


def _normalise_marker_name(name: str) -> str:
    return name.replace("-", "_")


def _normalise_prefix(value: str) -> str:
    value = value.replace("\\", "/").strip()
    return value.rstrip("/")


def _path_matches_prefixes(path: str, prefixes: Sequence[str]) -> bool:
    return any(path == prefix or path.startswith(f"{prefix}/") for prefix in prefixes)


_SUITE_STASH_KEY = object()


@dataclass(frozen=True)
class SuiteDefinition:
    """Describe how a logical test suite should filter collected tests."""

    name: str
    include_any: Sequence[str] = ()
    exclude_any: Sequence[str] = ()
    include_by_default: bool = True
    include_paths: Sequence[str] = ()
    exclude_paths: Sequence[str] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "_include_normalised",
            {_normalise_marker_name(name) for name in self.include_any},
        )
        object.__setattr__(
            self,
            "_exclude_normalised",
            {_normalise_marker_name(name) for name in self.exclude_any},
        )
        object.__setattr__(
            self,
            "_include_paths",
            tuple(_normalise_prefix(path) for path in self.include_paths),
        )
        object.__setattr__(
            self,
            "_exclude_paths",
            tuple(_normalise_prefix(path) for path in self.exclude_paths),
        )

    def should_run(self, item: pytest.Item) -> bool:
        markers = {_normalise_marker_name(marker.name) for marker in item.iter_markers()}
        include = self._include_normalised
        exclude = self._exclude_normalised
        path = item.nodeid.split("::", 1)[0].replace("\\", "/")

        if include and markers & include:
            return True
        if self._include_paths and _path_matches_prefixes(path, self._include_paths):
            return True

        if not self.include_by_default:
            return False

        if markers & exclude:
            return False
        if self._exclude_paths and _path_matches_prefixes(path, self._exclude_paths):
            return False

        return True


SUITES: Mapping[str, SuiteDefinition] = {
    "core": SuiteDefinition(
        name="core",
        exclude_any=("gui", "gui_smoke", "gui_full", "real_llm", "slow", "quality"),
        exclude_paths=(
            "tests/gui",
            "tests/slow",
        ),
    ),
    "service": SuiteDefinition(
        name="service",
        exclude_any=("gui", "gui_smoke", "gui_full", "real_llm", "quality"),
        exclude_paths=("tests/gui",),
    ),
    "real-llm": SuiteDefinition(
        name="real-llm",
        include_any=("real_llm",),
        include_by_default=False,
        include_paths=("tests/integration/test_llm_openrouter_integration.py",),
    ),
    "gui-smoke": SuiteDefinition(
        name="gui-smoke",
        include_any=("gui_smoke",),
        include_by_default=False,
        include_paths=("tests/gui",),
    ),
    "gui-full": SuiteDefinition(
        name="gui-full",
        include_any=("gui_full",),
        include_by_default=False,
        include_paths=("tests/gui",),
    ),
    "quality": SuiteDefinition(
        name="quality",
        include_any=("quality",),
        include_by_default=False,
    ),
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--suite",
        action="store",
        choices=sorted(SUITES),
        help="Select the logical test suite to run",
    )


def pytest_configure(config: pytest.Config) -> None:
    suite_name = config.getoption("--suite")
    if suite_name is None:
        return
    config.stash[_SUITE_STASH_KEY] = SUITES[suite_name]
    config.addinivalue_line(
        "markers",
        "suite_selected(name): internal marker documenting the active suite",
    )
    config.pluginmanager.register(_SuiteReporter(suite_name), name="cookareq-suite-reporter")


class _SuiteReporter:
    def __init__(self, suite_name: str) -> None:
        self._suite_name = suite_name

    def pytest_report_header(self, config: pytest.Config) -> list[str]:  # pragma: no cover - UI detail
        return [f"CookaReq test suite: {self._suite_name}"]


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    suite = config.stash.get(_SUITE_STASH_KEY, None)
    if suite is None:
        return

    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        if suite.should_run(item):
            item.add_marker(pytest.mark.suite_selected(suite.name))
            selected.append(item)
        else:
            deselected.append(item)

    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


def _reset_wx_config(wx: ModuleType) -> None:
    """Clear the global wx config instance so a new one picks up our env."""

    config = wx.ConfigBase.Get()
    if config is None:
        return

    with contextlib.suppress(Exception):
        config.Flush()
    wx.ConfigBase.Set(None)


def _destroy_top_windows(wx: ModuleType) -> None:
    """Hide and destroy any lingering top-level windows."""

    for window in list(wx.GetTopLevelWindows()):
        if not window:
            continue
        with contextlib.suppress(Exception):
            window.Hide()
            window.Destroy()


@pytest.fixture(scope="session")
def _wx_session_app(request: pytest.FixtureRequest, xvfb: None) -> tuple[ModuleType, "wx.App"]:
    """Create a shared ``wx.App`` guarded by the xvfb fixture."""

    wx = pytest.importorskip("wx")
    app = wx.App()
    _install_safe_yield(app)

    def _finalise() -> None:
        _destroy_top_windows(wx)
        _reset_wx_config(wx)
        with contextlib.suppress(Exception):
            app.Destroy()

    request.addfinalizer(_finalise)
    return wx, app


def _install_safe_yield(app: "wx.App") -> None:
    """Replace ``wx.App.Yield`` with a crash-resistant event pump."""

    if not hasattr(app, "HasPendingEvents") or not hasattr(app, "ProcessPendingEvents"):
        return

    def _safe_yield(self: "wx.App", *args, **kwargs) -> None:
        for _ in range(5):
            had_events = False
            while self.HasPendingEvents():
                had_events = True
                self.ProcessPendingEvents()
            if not had_events:
                break

    app.Yield = MethodType(_safe_yield, app)


@pytest.fixture
def wx_app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
    _wx_session_app: tuple[ModuleType, "wx.App"],
) -> "wx.App":
    """Return a ``wx.App`` instance with per-test isolation for configs."""

    wx, app = _wx_session_app

    config_root = tmp_path_factory.mktemp("wx-config")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_root))

    _reset_wx_config(wx)
    _destroy_top_windows(wx)

    yield app

    _destroy_top_windows(wx)
    _reset_wx_config(wx)
