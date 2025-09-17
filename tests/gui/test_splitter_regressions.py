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
