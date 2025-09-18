"""Regression test for widening layout after repeated restarts."""

from __future__ import annotations

from pathlib import Path

import wx

from app.config import ConfigManager
from app.settings import MCPSettings
from app.ui.main_frame import MainFrame
from app.ui.requirement_model import RequirementModel


def _open_frame(config_path: Path, wx_app) -> MainFrame:
    """Create ``MainFrame`` bound to configuration stored at ``config_path``."""

    config = ConfigManager(path=config_path)
    config.set_mcp_settings(MCPSettings(auto_start=False))
    frame = MainFrame(None, config=config, model=RequirementModel())
    frame.Show()
    wx_app.Yield()
    return frame


def test_hierarchy_and_agent_history_width_do_not_expand(wx_app, tmp_path):
    """Ensure sash widths remain stable across consecutive sessions."""

    config_path = tmp_path / "layout.ini"
    doc_tree_widths: list[int] = []
    history_widths: list[int] = []

    for _ in range(4):
        frame = _open_frame(config_path, wx_app)
        if not frame.agent_splitter.IsSplit():
            menu = frame.agent_chat_menu_item
            assert menu is not None
            menu.Check(True)
            frame.on_toggle_agent_chat(None)
            wx_app.Yield()
        width = frame.doc_tree_container.GetSize().width
        if width <= 0:
            width = frame.doc_tree_container.GetClientSize().width
        doc_tree_widths.append(width)
        history_splitter = frame.agent_panel._horizontal_splitter
        wx_app.Yield()
        history_panel = history_splitter.GetWindow1()
        history_width = history_panel.GetSize().width
        if history_width <= 0:
            history_width = history_panel.GetClientSize().width
        history_widths.append(history_width)
        frame._save_layout()
        frame.Destroy()
        wx_app.Yield()

    assert doc_tree_widths[0] > 0
    assert history_widths[0] > 0
    assert doc_tree_widths == [doc_tree_widths[0]] * len(doc_tree_widths)
    assert history_widths == [history_widths[0]] * len(history_widths)


def test_splitter_widths_survive_window_resizing(wx_app, tmp_path):
    """Ensure sash widths stay constant even when the window is resized."""

    config_path = tmp_path / "resize.ini"
    doc_tree_widths: list[int] = []
    history_widths: list[int] = []

    for extra in range(6):
        frame = _open_frame(config_path, wx_app)
        frame.SetSize(wx.Size(800 + extra * 120, 640))
        wx_app.Yield()
        if not frame.agent_splitter.IsSplit():
            menu = frame.agent_chat_menu_item
            assert menu is not None
            menu.Check(True)
            frame.on_toggle_agent_chat(None)
            wx_app.Yield()
        width = frame.doc_tree_container.GetSize().width
        if width <= 0:
            width = frame.doc_tree_container.GetClientSize().width
        doc_tree_widths.append(width)
        history_splitter = frame.agent_panel._horizontal_splitter
        wx_app.Yield()
        history_panel = history_splitter.GetWindow1()
        history_width = history_panel.GetSize().width
        if history_width <= 0:
            history_width = history_panel.GetClientSize().width
        history_widths.append(history_width)
        frame.Close(True)
        wx_app.Yield()

    assert doc_tree_widths[0] > 0
    assert history_widths[0] > 0
    assert doc_tree_widths == [doc_tree_widths[0]] * len(doc_tree_widths)
    assert history_widths == [history_widths[0]] * len(history_widths)


def test_splitter_widths_ignore_sash_offset(wx_app, tmp_path):
    """Sash measurements that include decorations must not drift."""

    extra = 11
    config_path = tmp_path / "offset.ini"
    doc_tree_widths: list[int] = []
    history_widths: list[int] = []

    for _ in range(4):
        frame = _open_frame(config_path, wx_app)
        if not frame.agent_splitter.IsSplit():
            menu = frame.agent_chat_menu_item
            assert menu is not None
            menu.Check(True)
            frame.on_toggle_agent_chat(None)
            wx_app.Yield()
        doc_tree_widths.append(frame._current_doc_tree_width())
        history_splitter = frame.agent_panel._horizontal_splitter
        history_panel = history_splitter.GetWindow1()
        width = history_panel.GetSize().width
        if width <= 0:
            width = history_panel.GetClientSize().width
        history_widths.append(width)
        doc_splitter = frame.doc_splitter
        agent_splitter = frame.agent_splitter
        doc_original = doc_splitter.GetSashPosition
        agent_original = agent_splitter.GetSashPosition
        history_original = history_splitter.GetSashPosition

        def doc_fake() -> int:
            measured = frame.doc_tree_container.GetSize().width
            if measured <= 0:
                measured = frame.doc_tree_container.GetClientSize().width
            if measured <= 0:
                measured = doc_original()
            return measured + extra

        def agent_fake() -> int:
            primary = agent_splitter.GetWindow1()
            measured = primary.GetSize().width if primary else 0
            if measured <= 0 and primary is not None:
                measured = primary.GetClientSize().width
            if measured <= 0:
                measured = agent_original()
            return measured + extra

        def history_fake() -> int:
            measured = history_panel.GetSize().width
            if measured <= 0:
                measured = history_panel.GetClientSize().width
            if measured <= 0:
                measured = history_original()
            return measured + extra

        doc_splitter.GetSashPosition = doc_fake  # type: ignore[assignment]
        agent_splitter.GetSashPosition = agent_fake  # type: ignore[assignment]
        history_splitter.GetSashPosition = history_fake  # type: ignore[assignment]
        try:
            frame._save_layout()
        finally:
            doc_splitter.GetSashPosition = doc_original  # type: ignore[assignment]
            agent_splitter.GetSashPosition = agent_original  # type: ignore[assignment]
            history_splitter.GetSashPosition = history_original  # type: ignore[assignment]
        frame.Destroy()
        wx_app.Yield()

    assert doc_tree_widths[0] > 0
    assert history_widths[0] > 0
    assert doc_tree_widths == [doc_tree_widths[0]] * len(doc_tree_widths)
    assert history_widths == [history_widths[0]] * len(history_widths)


def test_log_console_sash_respects_minimum_top_height(wx_app, tmp_path):
    """Restore log console with collapsed sash must keep list visible."""

    config_path = tmp_path / "log_min.ini"
    config = ConfigManager(path=config_path)
    config.set_mcp_settings(MCPSettings(auto_start=False))
    config.set_value("log_shown", True)
    config.set_value("log_sash", 1)
    config.flush()

    frame = _open_frame(config_path, wx_app)
    try:
        doc_min = frame.doc_splitter.GetEffectiveMinSize().height
        if doc_min <= 0:
            doc_min = frame.main_splitter.FromDIP(200)
        doc_min = max(int(doc_min), 1)

        sash = frame.main_splitter.GetSashPosition()
        assert sash == frame.doc_splitter.GetSize().height
        assert sash >= doc_min

        list_min = frame.panel.list.GetEffectiveMinSize().height
        if list_min > 0:
            assert frame.panel.list.GetClientSize().height >= list_min
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_log_console_sash_respects_minimum_bottom_height(wx_app, tmp_path):
    """Restore log console with oversized sash keeps console usable."""

    config_path = tmp_path / "log_max.ini"
    config = ConfigManager(path=config_path)
    config.set_mcp_settings(MCPSettings(auto_start=False))
    config.set_value("log_shown", True)
    config.set_value("log_sash", 50_000)
    config.flush()

    frame = _open_frame(config_path, wx_app)
    try:
        total_height = frame.main_splitter.GetClientSize().height
        log_min = frame.log_panel.GetEffectiveMinSize().height
        if log_min <= 0:
            log_min = frame.main_splitter.FromDIP(120)
        log_min = max(int(log_min), 1)

        sash = frame.main_splitter.GetSashPosition()
        remaining = total_height - sash
        assert remaining >= log_min

        log_height = frame.log_panel.GetSize().height
        assert log_height > 0
    finally:
        frame.Destroy()
        wx_app.Yield()
