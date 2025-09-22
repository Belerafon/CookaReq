"""Regression tests covering splitter layout interactions in the main frame."""

from __future__ import annotations
import pytest

from app.config import ConfigManager


pytestmark = pytest.mark.gui


def _layout_constraints(frame, *, agent_visible: bool, editor_visible: bool) -> tuple[int, int, int, int]:
    """Return (doc_min, requirements_min, agent_min, doc_max) for current frame."""

    doc_min = max(frame.doc_splitter.GetMinimumPaneSize(), 100)
    requirements_min = max(frame.splitter.GetMinimumPaneSize(), 1)
    if editor_visible:
        requirements_min *= 2
    agent_min = max(frame.agent_splitter.GetMinimumPaneSize(), 1)
    if agent_visible:
        right_min = max(agent_min, requirements_min) + agent_min
    else:
        right_min = requirements_min
    total_width = frame.doc_splitter.GetClientSize().width
    assert total_width > 0
    doc_max = max(total_width - right_min, doc_min)
    return doc_min, requirements_min, agent_min, doc_max


def test_layout_restore_clamps_nested_splitters(wx_app, tmp_path):
    """The hierarchy splitter honours nested minima when state is restored."""

    wx = pytest.importorskip("wx")
    from app.ui.main_frame import MainFrame

    config = ConfigManager(path=tmp_path / "layout.ini")
    config.set_doc_tree_shown(True)
    config.set_doc_tree_sash(5000)
    config.set_agent_chat_shown(True)
    config.set_agent_chat_sash(5)

    frame = MainFrame(None, config=config)
    frame.Show()
    wx_app.Yield()

    try:
        agent_visible = frame._is_agent_chat_visible()
        editor_visible = frame._is_editor_visible()
        doc_min, requirements_min, agent_min, doc_max = _layout_constraints(
            frame,
            agent_visible=agent_visible,
            editor_visible=editor_visible,
        )

        assert agent_visible
        assert frame.agent_splitter.IsSplit()

        tolerance = max(frame.FromDIP(8), 1)
        doc_sash = frame.doc_splitter.GetSashPosition()
        assert doc_min <= doc_sash <= doc_max
        assert doc_max - doc_sash <= tolerance
        assert frame._doc_tree_last_sash == doc_sash

        agent_sash = frame.agent_splitter.GetSashPosition()
        agent_region = frame.agent_splitter.GetClientSize().width - agent_sash
        assert agent_sash >= agent_min
        assert agent_region >= agent_min
        assert frame._agent_last_sash == agent_sash
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_agent_toggle_reduces_wide_hierarchy(wx_app, tmp_path):
    """Enabling the agent pane shrinks an oversized hierarchy region."""

    wx = pytest.importorskip("wx")
    from app.ui.main_frame import MainFrame

    config = ConfigManager(path=tmp_path / "toggle.ini")
    config.set_doc_tree_shown(True)
    config.set_agent_chat_shown(False)

    frame = MainFrame(None, config=config)
    frame.Show()
    wx_app.Yield()

    try:
        agent_visible = frame._is_agent_chat_visible()
        editor_visible = frame._is_editor_visible()
        doc_min, requirements_min, agent_min, doc_max_without_agent = _layout_constraints(
            frame,
            agent_visible=agent_visible,
            editor_visible=editor_visible,
        )

        frame.doc_splitter.SetSashPosition(doc_max_without_agent)
        frame._doc_tree_last_sash = frame.doc_splitter.GetSashPosition()

        frame.agent_chat_menu_item.Check(True)
        frame._apply_agent_chat_visibility(persist=False)
        wx_app.Yield()

        agent_visible = frame._is_agent_chat_visible()
        assert agent_visible

        doc_min, requirements_min, agent_min, doc_max = _layout_constraints(
            frame,
            agent_visible=agent_visible,
            editor_visible=editor_visible,
        )
        tolerance = max(frame.FromDIP(8), 1)
        doc_sash = frame.doc_splitter.GetSashPosition()
        assert doc_min <= doc_sash <= doc_max
        assert doc_max - doc_sash <= tolerance
        assert frame._doc_tree_last_sash == doc_sash

        agent_sash = frame.agent_splitter.GetSashPosition()
        agent_region = frame.agent_splitter.GetClientSize().width - agent_sash
        assert agent_sash >= agent_min
        assert agent_region >= agent_min
        assert frame._agent_last_sash == agent_sash
    finally:
        frame.Destroy()
        wx_app.Yield()
