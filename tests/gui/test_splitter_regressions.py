"""Regression tests for splitter sash persistence and toggles."""

import wx
import pytest

import app.ui.list_panel as list_panel
from app.config import ConfigManager
from app.settings import MCPSettings
from app.ui.main_frame import MainFrame
from app.ui.requirement_model import RequirementModel


def _pane_width(window: wx.Window) -> int:
    width = window.GetSize().width
    if width <= 0:
        width = window.GetClientSize().width
    return width


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
    """Collapsing and expanding the hierarchy keeps the previous width."""

    frame, _ = configured_frame("doc_tree.ini")
    initial = _pane_width(frame.doc_tree_container)

    for _ in range(4):
        frame._collapse_doc_tree()
        wx_app.Yield()
        collapsed = _pane_width(frame.doc_tree_container)
        assert collapsed < initial
        assert frame._doc_tree_collapsed is True

        frame._expand_doc_tree()
        wx_app.Yield()
        restored = _pane_width(frame.doc_tree_container)
        tolerance = frame.doc_tree_container.FromDIP(4)
        assert abs(restored - initial) <= tolerance
        assert frame._doc_tree_collapsed is False

    frame.Destroy()
    wx_app.Yield()


def test_agent_chat_toggle_preserves_width(configured_frame, wx_app):
    """Showing and hiding agent chat keeps a consistent splitter width."""

    frame, _ = configured_frame("agent.ini")
    menu = frame.agent_chat_menu_item
    assert menu is not None

    expected = None
    for _ in range(4):
        menu.Check(True)
        frame.on_toggle_agent_chat(None)
        wx_app.Yield()
        assert frame.agent_splitter.IsSplit()
        assert isinstance(frame.agent_panel, list_panel.ListPanel)
        sash_width = frame._current_agent_splitter_width()
        tolerance = (
            frame.agent_splitter.FromDIP(4)
            if hasattr(frame.agent_splitter, "FromDIP")
            else 4
        )
        if expected is None:
            expected = sash_width
        else:
            assert abs(sash_width - expected) <= tolerance
        assert abs(frame._agent_last_width - expected) <= tolerance
        list_ctrl = frame.agent_panel.list
        assert _pane_width(list_ctrl) > 0

        menu.Check(False)
        frame.on_toggle_agent_chat(None)
        wx_app.Yield()
        assert not frame.agent_splitter.IsSplit()
        assert abs(frame._agent_last_width - expected) <= tolerance

    frame.Destroy()
    wx_app.Yield()


def test_debug_requirement_list_survives_layout_changes(configured_frame, wx_app):
    """Collapsing hierarchy must not disturb the debug requirement list."""

    frame, _ = configured_frame("agent_history.ini")
    menu = frame.agent_chat_menu_item
    assert menu is not None

    menu.Check(True)
    frame.on_toggle_agent_chat(None)
    wx_app.Yield()

    assert isinstance(frame.agent_panel, list_panel.ListPanel)
    list_ctrl = frame.agent_panel.list
    initial_count = list_ctrl.GetItemCount()
    initial_first = list_ctrl.GetItemText(0) if initial_count else None

    for _ in range(4):
        frame._collapse_doc_tree()
        wx_app.Yield()
        frame._expand_doc_tree()
        wx_app.Yield()
        assert list_ctrl.GetItemCount() == initial_count
        if initial_count:
            assert list_ctrl.GetItemText(0) == initial_first

    frame.Destroy()
    wx_app.Yield()
