from __future__ import annotations

from contextlib import suppress
import shutil
from pathlib import Path

import pytest


pytestmark = [pytest.mark.gui, pytest.mark.integration]


def _copy_demo_project(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[2] / "requirements" / "DEMO"
    destination = tmp_path / "demo_project"
    shutil.copytree(source, destination)
    return destination


def _create_main_frame(tmp_path: Path, context):
    wx = pytest.importorskip("wx")
    from app.config import ConfigManager
    from app.settings import MCPSettings
    from app.ui.main_frame import MainFrame
    from app.ui.requirement_model import RequirementModel

    config_path = tmp_path / "integration.ini"
    config = ConfigManager(path=config_path)
    config.set_mcp_settings(MCPSettings(auto_start=False))
    frame = MainFrame(
        None,
        context=context,
        config=config,
        model=RequirementModel(),
    )
    frame.Show()
    return frame


def _flush_events(app, count: int = 3) -> None:
    for _ in range(count):
        app.Yield()


def _click_history_row(wx, app, list_ctrl, row: int) -> None:
    item = list_ctrl.RowToItem(row)
    assert item and item.IsOk(), "expected history row to resolve to a DataViewItem"
    with suppress(Exception):
        list_ctrl.SetCurrentItem(item)
    client = list_ctrl.GetClientRect()
    width = client.GetWidth()
    height = client.GetHeight()
    if width <= 0 or height <= 0:
        list_ctrl.SetMinSize(wx.Size(300, 200))
        parent = list_ctrl.GetTopLevelParent()
        if parent:
            parent.SendSizeEvent()
        _flush_events(app, 3)
        client = list_ctrl.GetClientRect()
        width = client.GetWidth()
        height = client.GetHeight()
    if width <= 0 or height <= 0:
        raise AssertionError("history list has no visible size")

    def _row_selected() -> bool:
        try:
            selections = list_ctrl.GetSelections()
        except Exception:
            selections = []
        for selection in selections:
            if not selection or not selection.IsOk():
                continue
            try:
                if list_ctrl.ItemToRow(selection) == row:
                    return True
            except Exception:
                continue
        return False

    x = client.GetLeft() + max(min(width // 3, width - 8), 8)
    sim = wx.UIActionSimulator()
    hit_point: wx.Point | None = None
    for offset_y in range(height):
        y = client.GetTop() + offset_y
        candidate = wx.Point(x, y)
        screen = list_ctrl.ClientToScreen(candidate)
        sim.MouseMove(screen.x, screen.y)
        _flush_events(app, 1)
        sim.MouseDown(wx.MOUSE_BTN_LEFT)
        _flush_events(app, 1)
        sim.MouseUp(wx.MOUSE_BTN_LEFT)
        _flush_events(app, 2)
        if _row_selected():
            hit_point = candidate
            break
        list_ctrl.UnselectAll()
        _flush_events(app, 1)
    if hit_point is None:
        raise AssertionError("failed to select history row via simulated click")


def test_demo_history_archive_activates_on_click(tmp_path, wx_app, gui_context):
    wx = pytest.importorskip("wx")
    project_dir = _copy_demo_project(tmp_path)
    frame = _create_main_frame(tmp_path, gui_context)
    try:
        frame.SetSize((1024, 768))
        frame.SendSizeEvent()
        if frame.agent_chat_menu_item and not frame.agent_chat_menu_item.IsChecked():
            frame.agent_chat_menu_item.Check(True)
            frame.on_toggle_agent_chat(None)
            _flush_events(wx_app, 3)
        _flush_events(wx_app)
        frame._load_directory(project_dir)
        _flush_events(wx_app, 10)

        panel = frame.agent_panel
        history_list = panel.history_list

        expected_history_path = project_dir / ".cookareq" / "agent_chats.sqlite"
        assert expected_history_path.exists(), "seed archive should extract into .cookareq"
        assert panel.history_path == expected_history_path

        history_model = panel._session.history
        draft_id = history_model.active_id
        assert draft_id is not None, "a fresh draft conversation should be active"

        seeded_index = None
        for idx, conversation in enumerate(history_model.conversations):
            if conversation.entries:
                seeded_index = idx
                break
        assert seeded_index is not None, "expected to find a seeded conversation with entries"

        history_list.SetFocus()
        history_list.EnsureVisible(history_list.RowToItem(seeded_index))
        history_list.Update()
        frame.SendSizeEvent()
        _flush_events(wx_app, 4)
        history_list.UnselectAll()
        _flush_events(wx_app, 2)

        _click_history_row(wx, wx_app, history_list, seeded_index)
        _flush_events(wx_app, 5)
        assert history_list.IsRowSelected(seeded_index)
        assert panel.active_conversation_id != draft_id
        seeded_entries = panel.history
        assert seeded_entries, "seeded conversation entries should load"
        first_entry = seeded_entries[0]
        assert first_entry.prompt.startswith("Переведи"), "unexpected prompt in seeded history"
        assert first_entry.response, "seeded response should not be empty"
    finally:
        frame.Destroy()
        _flush_events(wx_app)
