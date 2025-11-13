"""Tests for synchronising MCP base path with the opened directory."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.application import ApplicationContext


pytestmark = pytest.mark.gui


class _StubMCP:
    """Minimal stand-in for :class:`MCPController`."""

    def __init__(self) -> None:
        self.start_calls: list[str] = []
        self.stop_calls = 0
        self._running = False

    def start(
        self,
        settings,
        *,
        max_context_tokens: int,
        token_model: str | None,
    ) -> None:  # pragma: no cover - simple recorder
        del max_context_tokens, token_model
        self.start_calls.append(settings.base_path)
        self._running = True

    def stop(self) -> None:  # pragma: no cover - simple recorder
        self.stop_calls += 1
        self._running = False

    def is_running(self) -> bool:  # pragma: no cover - simple recorder
        return self._running


def _make_frame(tmp_path, *, auto_start: bool):
    pytest.importorskip("wx")
    import app.ui.main_frame as main_frame_module
    from app.config import ConfigManager
    from app.settings import MCPSettings
    from app.ui.requirement_model import RequirementModel

    config_path = tmp_path / ("config_auto.ini" if auto_start else "config_manual.ini")
    config = ConfigManager(path=config_path)
    config.set_mcp_settings(MCPSettings(auto_start=auto_start, base_path=""))
    frame = main_frame_module.MainFrame(
        None,
        context=ApplicationContext.for_gui(),
        config=config,
        model=RequirementModel(),
        mcp_factory=_StubMCP,
    )
    return frame, config


def _sample_requirements_dir() -> Path:
    return (Path(__file__).resolve().parents[1] / "requirements").resolve()


def test_load_directory_updates_mcp_base_path(tmp_path, wx_app):
    """Opening a directory should persist it as the MCP base path."""

    frame, config = _make_frame(tmp_path, auto_start=False)
    try:
        repo = _sample_requirements_dir()
        frame._load_directory(repo)

        expected = str(repo)
        assert frame.mcp_settings.base_path == expected
        assert config.get_mcp_settings().base_path == expected
        assert frame.mcp.start_calls == []
        assert frame.mcp.stop_calls == 0
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_auto_start_restarts_mcp_with_new_base_path(tmp_path, wx_app):
    """When MCP auto-start is enabled the server should restart for new paths."""

    frame, config = _make_frame(tmp_path, auto_start=True)
    stub = frame.mcp
    try:
        assert stub.start_calls == []

        repo = _sample_requirements_dir()
        frame._load_directory(repo)

        expected = str(repo)
        assert stub.stop_calls == 0
        assert stub.start_calls == [expected]
        assert frame.mcp_settings.base_path == expected
        assert config.get_mcp_settings().base_path == expected
    finally:
        frame.Destroy()
        wx_app.Yield()
