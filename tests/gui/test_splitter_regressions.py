"""Regression tests for splitter sash persistence and toggles."""

import wx
import pytest

import app.ui.list_panel as list_panel
from app.config import ConfigManager
from app.core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
)
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


def _make_requirement(req_id: int, title: str) -> Requirement:
    """Create a simple requirement instance for main list mutations."""

    return Requirement(
        id=req_id,
        title=title,
        statement=title,
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="tester",
        priority=Priority.MEDIUM,
        source="unit-test",
        verification=Verification.ANALYSIS,
    )


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


def test_debug_requirement_list_remains_static_when_main_changes(configured_frame, wx_app):
    """Updating the primary requirement list must not affect the debug data."""

    frame, _ = configured_frame("agent_static.ini")
    menu = frame.agent_chat_menu_item
    assert menu is not None

    menu.Check(True)
    frame.on_toggle_agent_chat(None)
    wx_app.Yield()

    assert isinstance(frame.agent_panel, list_panel.ListPanel)
    debug_ctrl = frame.agent_panel.list
    expected_titles = [
        "Debug requirement A",
        "Debug requirement B",
        "Debug requirement C",
    ]

    initial_titles = [
        debug_ctrl.GetItemText(i) for i in range(debug_ctrl.GetItemCount())
    ]
    assert initial_titles == expected_titles

    frame.panel.set_requirements(
        [
            _make_requirement(1, "Primary requirement 1"),
            _make_requirement(2, "Primary requirement 2"),
        ]
    )
    wx_app.Yield()

    final_titles = [
        debug_ctrl.GetItemText(i) for i in range(debug_ctrl.GetItemCount())
    ]
    assert final_titles == expected_titles

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
    assert frame.agent_panel.columns == ["status", "owner"]
    expected_titles = [
        "Debug requirement A",
        "Debug requirement B",
        "Debug requirement C",
    ]
    expected_statuses = ["Draft", "In review", "Approved"]
    expected_owners = ["Alpha", "Beta", "Gamma"]

    for _ in range(4):
        assert list_ctrl.GetItemCount() == 3
        titles = [list_ctrl.GetItemText(i) for i in range(list_ctrl.GetItemCount())]
        statuses = [list_ctrl.GetItemText(i, 1) for i in range(list_ctrl.GetItemCount())]
        owners = [list_ctrl.GetItemText(i, 2) for i in range(list_ctrl.GetItemCount())]
        assert titles == expected_titles
        assert statuses == expected_statuses
        assert owners == expected_owners
        frame._collapse_doc_tree()
        wx_app.Yield()
        frame._expand_doc_tree()
        wx_app.Yield()
        assert list_ctrl.GetItemCount() == 3
        titles_after = [
            list_ctrl.GetItemText(i) for i in range(list_ctrl.GetItemCount())
        ]
        statuses_after = [
            list_ctrl.GetItemText(i, 1) for i in range(list_ctrl.GetItemCount())
        ]
        owners_after = [
            list_ctrl.GetItemText(i, 2) for i in range(list_ctrl.GetItemCount())
        ]
        assert titles_after == expected_titles
        assert statuses_after == expected_statuses
        assert owners_after == expected_owners

    frame.Destroy()
    wx_app.Yield()
