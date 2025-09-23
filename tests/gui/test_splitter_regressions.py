import pytest
import wx

from app.config import ConfigManager
from app.settings import MCPSettings
from app.ui.main_frame import MainFrame
from app.ui.requirement_model import RequirementModel


@pytest.fixture
def configured_frame(wx_app, tmp_path):
    """Create a ``MainFrame`` with isolated configuration storage."""

    created: list[MainFrame] = []

    def _factory(name: str = "layout.ini"):
        config_path = tmp_path / name
        config = ConfigManager(path=config_path)
        config.set_mcp_settings(MCPSettings(auto_start=False))
        frame = MainFrame(None, config=config, model=RequirementModel())
        frame.Show()
        wx_app.Yield()
        created.append(frame)
        return frame, config_path

    try:
        yield _factory
    finally:
        for frame in created:
            if frame and not frame.IsBeingDeleted():
                frame.Destroy()
                wx_app.Yield()


def test_hierarchy_toggle_keeps_width(configured_frame, wx_app):
    frame, _ = configured_frame("hierarchy.ini")
    initial = frame.doc_splitter.GetSashPosition()

    frame.hierarchy_menu_item.Check(False)
    frame.on_toggle_hierarchy(None)
    wx_app.Yield()

    frame.hierarchy_menu_item.Check(True)
    frame.on_toggle_hierarchy(None)
    wx_app.Yield()

    assert frame.doc_splitter.GetSashPosition() == initial


def test_hierarchy_state_persists_between_sessions(configured_frame, wx_app):
    frame, config_path = configured_frame("hierarchy_persist.ini")

    base = frame.doc_splitter.GetSashPosition()
    minimum = frame.doc_splitter.GetMinimumPaneSize()
    target = max(base + frame.FromDIP(120), minimum + frame.FromDIP(40))
    frame.doc_splitter.SetSashPosition(target)
    wx_app.Yield()

    frame.hierarchy_menu_item.Check(False)
    frame.on_toggle_hierarchy(None)
    wx_app.Yield()

    frame._save_layout()
    frame.Destroy()
    wx_app.Yield()

    config = ConfigManager(path=config_path)
    config.set_mcp_settings(MCPSettings(auto_start=False))
    restored = MainFrame(None, config=config, model=RequirementModel())
    restored.Show()
    wx_app.Yield()

    assert not restored.hierarchy_menu_item.IsChecked()
    assert not restored.doc_splitter.IsSplit()

    restored.hierarchy_menu_item.Check(True)
    restored.on_toggle_hierarchy(None)
    wx_app.Yield()

    assert restored.doc_splitter.GetSashPosition() == target
    restored.Destroy()
    wx_app.Yield()


def test_agent_chat_toggle_keeps_width(configured_frame, wx_app):
    frame, _ = configured_frame("agent.ini")

    frame.agent_chat_menu_item.Check(True)
    frame.on_toggle_agent_chat(None)
    wx_app.Yield()

    start = frame.agent_splitter.GetSashPosition()
    new_width = max(start - frame.FromDIP(100), frame.agent_splitter.GetMinimumPaneSize())
    frame.agent_splitter.SetSashPosition(new_width)
    wx_app.Yield()

    frame.agent_chat_menu_item.Check(False)
    frame.on_toggle_agent_chat(None)
    wx_app.Yield()

    frame.agent_chat_menu_item.Check(True)
    frame.on_toggle_agent_chat(None)
    wx_app.Yield()

    assert frame.agent_splitter.GetSashPosition() == new_width


def test_agent_state_persists_between_sessions(configured_frame, wx_app):
    frame, config_path = configured_frame("agent_persist.ini")

    frame.agent_chat_menu_item.Check(True)
    frame.on_toggle_agent_chat(None)
    wx_app.Yield()

    width = max(frame.agent_splitter.GetSashPosition() + frame.FromDIP(80), frame.agent_splitter.GetMinimumPaneSize())
    frame.agent_splitter.SetSashPosition(width)
    wx_app.Yield()

    frame._save_layout()
    frame.Destroy()
    wx_app.Yield()

    config = ConfigManager(path=config_path)
    config.set_mcp_settings(MCPSettings(auto_start=False))
    restored = MainFrame(None, config=config, model=RequirementModel())
    restored.Show()
    wx_app.Yield()

    assert restored.agent_chat_menu_item.IsChecked() is config.get_agent_chat_shown()
    assert restored.agent_splitter.GetSashPosition() == width

    restored.agent_chat_menu_item.Check(False)
    restored.on_toggle_agent_chat(None)
    wx_app.Yield()

    assert not restored.agent_splitter.IsSplit()
    restored.Destroy()
    wx_app.Yield()


def test_agent_history_apply_sash(configured_frame, wx_app):
    frame, _ = configured_frame("history.ini")

    frame.agent_chat_menu_item.Check(True)
    frame.on_toggle_agent_chat(None)
    wx_app.Yield()

    panel = frame.agent_panel
    splitter = panel._horizontal_splitter
    minimum = splitter.GetMinimumPaneSize()
    desired = minimum + panel.FromDIP(80)
    panel.apply_history_sash(desired)
    wx_app.Yield()

    assert panel.history_sash == splitter.GetSashPosition()
    assert panel.history_sash >= minimum


def test_agent_history_persists_between_sessions(configured_frame, wx_app):
    frame, config_path = configured_frame("history_persist.ini")

    frame.agent_chat_menu_item.Check(True)
    frame.on_toggle_agent_chat(None)
    wx_app.Yield()

    panel = frame.agent_panel
    splitter = panel._horizontal_splitter
    minimum = splitter.GetMinimumPaneSize()
    base = splitter.GetSashPosition()
    desired = max(base + frame.FromDIP(120), minimum + frame.FromDIP(40))
    splitter.SetSashPosition(desired)
    wx_app.Yield()

    assert panel.history_sash == desired

    frame._save_layout()
    frame.Destroy()
    wx_app.Yield()

    config = ConfigManager(path=config_path)
    config.set_mcp_settings(MCPSettings(auto_start=False))
    restored = MainFrame(None, config=config, model=RequirementModel())
    restored.Show()
    wx_app.Yield()

    assert restored.agent_chat_menu_item.IsChecked()
    restored_panel = restored.agent_panel
    restored_splitter = restored_panel._horizontal_splitter
    assert restored_panel.history_sash == desired
    assert restored_splitter.GetSashPosition() == desired
    restored.Destroy()
    wx_app.Yield()


def test_restore_limited_hierarchy_width(wx_app, tmp_path):
    """Huge stored hierarchy width shrinks so the agent pane stays visible."""

    config = ConfigManager(path=tmp_path / "clamp.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))
    config.set_doc_tree_shown(True)
    config.set_doc_tree_sash(5000)
    config.set_agent_chat_shown(True)
    config.set_agent_chat_sash(5)

    frame = MainFrame(None, config=config, model=RequirementModel())
    frame.Show()
    wx_app.Yield()

    try:
        assert frame.agent_chat_menu_item.IsChecked()
        doc_total = frame.doc_splitter.GetClientSize().width
        doc_min = max(frame.doc_splitter.GetMinimumPaneSize(), frame._doc_tree_min_pane, 1)
        list_min = max(frame.splitter.GetMinimumPaneSize(), 1)
        requirements_min = list_min * 2 if frame._is_editor_visible() else list_min
        agent_min = max(frame.agent_splitter.GetMinimumPaneSize(), 1)
        right_required = max(requirements_min, agent_min) + agent_min
        doc_max = max(doc_total - right_required, doc_min)
        doc_sash = frame.doc_splitter.GetSashPosition()
        assert doc_min <= doc_sash <= doc_max

        agent_total = frame.agent_splitter.GetClientSize().width
        agent_sash = frame.agent_splitter.GetSashPosition()
        requirements_left_min = max(frame.splitter.GetMinimumPaneSize(), agent_min)
        assert agent_sash >= requirements_left_min
        assert agent_total - agent_sash >= agent_min
    finally:
        frame.Destroy()
        wx_app.Yield()


def test_enabling_agent_shrinks_wide_hierarchy(wx_app, tmp_path):
    """Turning on the agent pane reduces an oversized hierarchy region."""

    config = ConfigManager(path=tmp_path / "toggle_clamp.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))
    config.set_doc_tree_shown(True)
    config.set_agent_chat_shown(False)

    frame = MainFrame(None, config=config, model=RequirementModel())
    frame.Show()
    wx_app.Yield()

    try:
        doc_total = frame.doc_splitter.GetClientSize().width
        doc_min = max(frame.doc_splitter.GetMinimumPaneSize(), frame._doc_tree_min_pane, 1)
        list_min = max(frame.splitter.GetMinimumPaneSize(), 1)
        requirements_min = list_min * 2 if frame._is_editor_visible() else list_min
        doc_max_without_agent = max(doc_total - requirements_min, doc_min)

        frame.doc_splitter.SetSashPosition(doc_max_without_agent)
        frame._doc_tree_last_sash = frame.doc_splitter.GetSashPosition()
        wx_app.Yield()

        frame.agent_chat_menu_item.Check(True)
        frame._apply_agent_chat_visibility(persist=False)
        wx_app.Yield()

        agent_min = max(frame.agent_splitter.GetMinimumPaneSize(), 1)
        right_required = max(requirements_min, agent_min) + agent_min
        doc_max = max(doc_total - right_required, doc_min)
        doc_sash = frame.doc_splitter.GetSashPosition()
        assert doc_min <= doc_sash <= doc_max

        agent_total = frame.agent_splitter.GetClientSize().width
        agent_sash = frame.agent_splitter.GetSashPosition()
        requirements_left_min = max(frame.splitter.GetMinimumPaneSize(), agent_min)
        assert agent_sash >= requirements_left_min
        assert agent_total - agent_sash >= agent_min
    finally:
        frame.Destroy()
        wx_app.Yield()
