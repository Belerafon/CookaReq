"""Regression tests for splitter sash persistence and toggles."""

import wx
import pytest

from app.config import ConfigManager
from app.settings import MCPSettings
from app.ui.main_frame import MainFrame
from app.ui.requirement_model import RequirementModel


def _pane_width(window: wx.Window) -> int:
    width = window.GetSize().width
    if width <= 0:
        width = window.GetClientSize().width
    return width


def _splitter_event(
    splitter: wx.SplitterWindow,
    event_type: int,
    pos: int,
) -> wx.SplitterEvent:
    event = wx.SplitterEvent(event_type, splitter)
    event.SetEventObject(splitter)
    event.SetSashPosition(pos)
    return event


@pytest.fixture
def configured_frame(wx_app, tmp_path):
    """Create a ``MainFrame`` with isolated configuration storage."""

    def _build(name: str = "layout.ini"):
        config_path = tmp_path / name
        config = ConfigManager(path=config_path)
        config.set_mcp_settings(MCPSettings(auto_start=False))
        frame = MainFrame(None, config=config, model=RequirementModel())
        frame.Show()
        wx_app.Yield()
        return frame, config_path

    created = []

    def _factory(name: str = "layout.ini"):
        frame, path = _build(name)
        created.append(frame)
        return frame, path

    try:
        yield _factory
    finally:
        for frame in created:
            if frame and not frame.IsBeingDeleted():
                frame.Destroy()
                wx_app.Yield()


def test_doc_tree_toggle_preserves_width(configured_frame, wx_app):
    """Collapsing and expanding the hierarchy must keep the stored width."""

    frame, config_path = configured_frame("doc_tree.ini")
    initial = frame.doc_splitter.GetSashPosition()

    for _ in range(5):
        frame._collapse_doc_tree(update_config=True)
        wx_app.Yield()
        frame._expand_doc_tree(update_config=True)
        wx_app.Yield()

    assert frame.doc_splitter.GetSashPosition() == initial
    assert frame._doc_tree_saved_width == initial

    frame._collapse_doc_tree(update_config=True)
    wx_app.Yield()
    frame._save_layout()
    frame.Destroy()
    wx_app.Yield()

    reloaded_config = ConfigManager(path=config_path)
    reloaded_config.set_mcp_settings(MCPSettings(auto_start=False))
    restored_frame = MainFrame(None, config=reloaded_config, model=RequirementModel())
    restored_frame.Show()
    wx_app.Yield()

    assert restored_frame._doc_tree_collapsed is True
    restored_frame._expand_doc_tree(update_config=False)
    wx_app.Yield()
    assert restored_frame.doc_splitter.GetSashPosition() == initial
    assert restored_frame._doc_tree_saved_width == initial

    restored_frame.Destroy()
    wx_app.Yield()


def test_doc_splitter_programmatic_move_is_ignored(configured_frame, wx_app):
    """Synthetic sash events without a drag must not overwrite saved width."""

    frame, _ = configured_frame("doc_programmatic.ini")
    initial = frame._doc_tree_saved_width
    bogus = initial + frame.FromDIP(300)

    event = _splitter_event(
        frame.doc_splitter,
        wx.wxEVT_SPLITTER_SASH_POS_CHANGED,
        bogus,
    )
    frame._on_doc_splitter_sash_changed(event)
    wx_app.Yield()

    assert frame._doc_tree_saved_width == initial


def test_doc_splitter_user_drag_persists_value(configured_frame, wx_app):
    """User drags update the saved width exactly once and persist to disk."""

    frame, config_path = configured_frame("doc_user_drag.ini")
    initial = frame._doc_tree_saved_width
    min_width = frame._doc_tree_min_pane + frame.FromDIP(40)
    new_width = max(min_width, initial - frame.FromDIP(160))
    client_width = frame.doc_splitter.GetClientSize().width
    if client_width > 0:
        max_allowed = client_width - frame._doc_tree_min_pane
        new_width = min(new_width, max_allowed)
    if new_width == initial:
        new_width = max(min_width, initial // 2)

    frame.doc_splitter.SetSashPosition(new_width)
    frame._on_doc_splitter_sash_changing(
        _splitter_event(
            frame.doc_splitter,
            wx.wxEVT_SPLITTER_SASH_POS_CHANGING,
            new_width,
        )
    )
    frame._on_doc_splitter_sash_changed(
        _splitter_event(
            frame.doc_splitter,
            wx.wxEVT_SPLITTER_SASH_POS_CHANGED,
            new_width,
        )
    )
    wx_app.Yield()

    assert frame._doc_tree_saved_width == new_width

    stray_width = min(new_width + frame.FromDIP(400), client_width or new_width + 1)
    frame._on_doc_splitter_sash_changed(
        _splitter_event(
            frame.doc_splitter,
            wx.wxEVT_SPLITTER_SASH_POS_CHANGED,
            stray_width,
        )
    )
    wx_app.Yield()

    assert frame._doc_tree_saved_width == new_width

    frame._save_layout()
    frame.Destroy()
    wx_app.Yield()

    reloaded_config = ConfigManager(path=config_path)
    reloaded_config.set_mcp_settings(MCPSettings(auto_start=False))
    restored_frame = MainFrame(
        None,
        config=reloaded_config,
        model=RequirementModel(),
    )
    restored_frame.Show()
    wx_app.Yield()

    assert restored_frame.doc_splitter.GetSashPosition() == new_width
    assert restored_frame._doc_tree_saved_width == new_width

    restored_frame.Destroy()
    wx_app.Yield()


def test_agent_chat_toggle_preserves_width(configured_frame, wx_app):
    """Showing and hiding agent chat must not drift the sash position."""

    frame, config_path = configured_frame("agent.ini")
    menu = frame.agent_chat_menu_item
    assert menu is not None

    expected = None
    for _ in range(4):
        menu.Check(True)
        frame.on_toggle_agent_chat(None)
        wx_app.Yield()
        assert frame.agent_splitter.IsSplit()
        visible = frame.agent_splitter.GetSashPosition()
        if expected is None:
            expected = visible
        else:
            assert visible == expected
        assert frame._agent_saved_sash == expected

        menu.Check(False)
        frame.on_toggle_agent_chat(None)
        wx_app.Yield()
        assert not frame.agent_splitter.IsSplit()
        assert frame._agent_saved_sash == expected

    frame._save_layout()
    frame.Destroy()
    wx_app.Yield()

    reloaded_config = ConfigManager(path=config_path)
    reloaded_config.set_mcp_settings(MCPSettings(auto_start=False))
    restored_frame = MainFrame(None, config=reloaded_config, model=RequirementModel())
    restored_frame.Show()
    wx_app.Yield()

    assert restored_frame._agent_saved_sash == expected
    restored_menu = restored_frame.agent_chat_menu_item
    assert restored_menu is not None
    restored_menu.Check(True)
    restored_frame.on_toggle_agent_chat(None)
    wx_app.Yield()

    assert restored_frame.agent_splitter.IsSplit()
    assert restored_frame.agent_splitter.GetSashPosition() == expected
    assert restored_frame._agent_saved_sash == expected

    restored_frame.Destroy()
    wx_app.Yield()


def test_agent_history_splitter_survives_layout_changes(configured_frame, wx_app):
    """Collapsing hierarchy must not resize the chat history column."""

    frame, config_path = configured_frame("agent_history.ini")
    menu = frame.agent_chat_menu_item
    assert menu is not None

    menu.Check(True)
    frame.on_toggle_agent_chat(None)
    wx_app.Yield()

    history_splitter = frame.agent_panel._horizontal_splitter
    initial = history_splitter.GetSashPosition()
    assert initial > 0

    for _ in range(4):
        frame._collapse_doc_tree(update_config=True)
        wx_app.Yield()
        frame._expand_doc_tree(update_config=True)
        wx_app.Yield()
        assert history_splitter.GetSashPosition() == initial
        assert frame.agent_panel.history_sash == initial

    frame._save_layout()
    frame.Destroy()
    wx_app.Yield()

    reloaded_config = ConfigManager(path=config_path)
    reloaded_config.set_mcp_settings(MCPSettings(auto_start=False))
    restored_frame = MainFrame(None, config=reloaded_config, model=RequirementModel())
    restored_frame.Show()
    wx_app.Yield()

    restored_menu = restored_frame.agent_chat_menu_item
    assert restored_menu is not None
    restored_menu.Check(True)
    restored_frame.on_toggle_agent_chat(None)
    wx_app.Yield()

    restored_splitter = restored_frame.agent_panel._horizontal_splitter
    assert restored_splitter.GetSashPosition() == initial
    assert restored_frame.agent_panel.history_sash == initial

    restored_frame.Destroy()
    wx_app.Yield()
