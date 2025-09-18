"""Regression tests for splitter sash persistence and toggles."""

import pytest

from app.config import ConfigManager
from app.settings import MCPSettings
from app.ui.main_frame import MainFrame
from app.ui.requirement_model import RequirementModel


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
    assert frame._doc_tree_saved_sash == initial

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
    assert restored_frame._doc_tree_saved_sash == initial

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


def test_doc_tree_ratio_scales_with_window(configured_frame, wx_app):
    """Saved doc tree ratio should adapt when the window width changes."""

    frame, config_path = configured_frame("doc_ratio.ini")
    wx_app.Yield()
    frame.doc_splitter.SetSashPosition(360)
    wx_app.Yield()
    frame._doc_tree_saved_sash = frame.doc_splitter.GetSashPosition()
    saved_sash = frame.doc_splitter.GetSashPosition()
    initial_width = max(frame.doc_splitter.GetClientSize().width, 1)
    initial_ratio = saved_sash / initial_width
    frame._save_layout()
    frame.Destroy()
    wx_app.Yield()

    config = ConfigManager(path=config_path)
    config.set_mcp_settings(MCPSettings(auto_start=False))
    current_width = config.get_value("win_w")
    config.set_value("win_w", current_width + 300)
    config.flush()

    restored_frame = MainFrame(None, config=config, model=RequirementModel())
    restored_frame.Show()
    wx_app.Yield()

    restored_width = max(restored_frame.doc_splitter.GetClientSize().width, 1)
    expected = restored_frame._resolve_doc_tree_sash(
        config.get_doc_tree_saved_sash(0), config.get_doc_tree_sash_ratio()
    )
    assert restored_frame.doc_splitter.GetSashPosition() == expected
    sash = restored_frame.doc_splitter.GetSashSize()
    available = max(restored_width - (sash if sash and sash > 0 else 0), 0)
    raw = int(round(restored_width * initial_ratio))
    max_left = max(available - restored_frame._doc_tree_min_pane, restored_frame._doc_tree_min_pane)
    target = max(restored_frame._doc_tree_min_pane, min(raw, max_left))
    assert expected == target
    if restored_width != initial_width and target != saved_sash:
        assert expected != saved_sash

    restored_frame.Destroy()
    wx_app.Yield()


def test_agent_ratio_scales_with_window(configured_frame, wx_app):
    """Agent chat sash must follow saved ratio when total width changes."""

    frame, config_path = configured_frame("agent_ratio.ini")
    menu = frame.agent_chat_menu_item
    assert menu is not None
    menu.Check(True)
    frame.on_toggle_agent_chat(None)
    wx_app.Yield()

    frame.agent_splitter.SetSashPosition(frame.agent_splitter.GetSashPosition() - 40)
    wx_app.Yield()
    frame._agent_saved_sash = frame.agent_splitter.GetSashPosition()
    saved_sash = frame.agent_splitter.GetSashPosition()
    agent_width = max(frame.agent_splitter.GetClientSize().width, 1)
    ratio = saved_sash / agent_width
    frame._save_layout()
    frame.Destroy()
    wx_app.Yield()

    config = ConfigManager(path=config_path)
    config.set_mcp_settings(MCPSettings(auto_start=False))
    current_width = config.get_value("win_w")
    config.set_value("win_w", current_width + 320)
    config.flush()

    restored_frame = MainFrame(None, config=config, model=RequirementModel())
    restored_frame.Show()
    wx_app.Yield()

    assert restored_frame.agent_splitter.IsSplit()
    restored_width = max(restored_frame.agent_splitter.GetClientSize().width, 1)
    stored_sash = config.get_agent_chat_sash(0)
    stored_ratio = config.get_agent_chat_sash_ratio()
    expected = restored_frame._resolve_agent_chat_sash(stored_sash, stored_ratio)
    assert restored_frame.agent_splitter.GetSashPosition() == expected
    sash = restored_frame.agent_splitter.GetSashSize()
    available = max(restored_width - (sash if sash and sash > 0 else 0), 0)
    min_size = max(restored_frame.agent_splitter.GetMinimumPaneSize(), 200)
    raw = int(round(restored_width * ratio))
    max_left = max(available - min_size, min_size)
    target = max(min_size, min(raw, max_left))
    assert expected == target
    if restored_width != agent_width and target != saved_sash:
        assert expected != saved_sash

    restored_frame.Destroy()
    wx_app.Yield()
