"""Tests for config manager."""

import pytest

from app.config import ConfigManager
from app.settings import AppSettings, LLMSettings, MCPSettings, UISettings

pytestmark = pytest.mark.unit


class DummyListPanel:
    def __init__(self):
        self.loaded_widths = False
        self.loaded_order = False
        self.saved_widths = False
        self.saved_order = False

    def load_column_widths(self, cfg: ConfigManager) -> None:
        self.loaded_widths = True

    def load_column_order(self, cfg: ConfigManager) -> None:
        self.loaded_order = True

    def save_column_widths(self, cfg: ConfigManager) -> None:
        self.saved_widths = True

    def save_column_order(self, cfg: ConfigManager) -> None:
        self.saved_order = True


@pytest.mark.parametrize("log_shown", [True, False])
def test_save_and_restore_layout(tmp_path, log_shown, wx_app):
    wx = pytest.importorskip("wx")
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    frame = wx.Frame(None)
    main_splitter = wx.SplitterWindow(frame)
    splitter = wx.SplitterWindow(main_splitter)
    splitter.SplitVertically(wx.Panel(splitter), wx.Panel(splitter))
    panel = DummyListPanel()
    log_console = wx.TextCtrl(main_splitter)

    if log_shown:
        log_console.Show()
        main_splitter.SplitHorizontally(splitter, log_console, 180)
    else:
        log_console.Hide()
        main_splitter.Initialize(splitter)

    frame.SetSize((900, 700))
    frame.SetPosition((10, 20))
    splitter.SetSashPosition(222)

    cfg.save_layout(frame, splitter, main_splitter, panel)

    assert panel.saved_widths and panel.saved_order
    assert cfg.ReadBool("log_shown") is log_shown

    new_frame = wx.Frame(None)
    new_main_splitter = wx.SplitterWindow(new_frame)
    new_splitter = wx.SplitterWindow(new_main_splitter)
    new_splitter.SplitVertically(wx.Panel(new_splitter), wx.Panel(new_splitter))
    new_panel = DummyListPanel()
    new_log = wx.TextCtrl(new_main_splitter)
    new_frame.Show()

    cfg.restore_layout(new_frame, new_splitter, new_main_splitter, new_panel, new_log)

    assert new_frame.GetSize() == (900, 700)
    assert new_frame.GetPosition() == (10, 20)
    assert new_panel.loaded_widths and new_panel.loaded_order

    if log_shown:
        assert new_splitter.GetSashPosition() == 222
        assert new_main_splitter.IsSplit()
        assert new_log.IsShown()
    else:
        assert new_splitter.GetSashPosition() > 0
        assert not new_main_splitter.IsSplit()
        assert not new_log.IsShown()


def test_app_settings_round_trip(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    app_settings = AppSettings(
        llm=LLMSettings(
            base_url="http://api",
            model="gpt",
            api_key="k",
            max_retries=2,
            max_output_tokens=100,
            timeout_minutes=42,
            stream=False,
        ),
        mcp=MCPSettings(host="1.2.3.4", port=9999, base_path="/m", require_token=True, token="t"),
        ui=UISettings(
            columns=["id", "title"],
            recent_dirs=[str(tmp_path / "a"), str(tmp_path / "b")],
            auto_open_last=True,
            remember_sort=True,
            language="ru",
            sort_column=2,
            sort_ascending=False,
        ),
    )

    cfg.set_app_settings(app_settings)
    loaded = cfg.get_app_settings()
    assert loaded == app_settings


def test_sort_settings_round_trip(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    cfg.set_sort_settings(3, False)
    assert cfg.get_sort_settings() == (3, False)
    assert cfg.ReadInt("sort_column") == 3
    assert cfg.ReadBool("sort_ascending") is False


def test_restore_layout_without_show(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    # Save initial layout with a known sash position
    frame = wx.Frame(None)
    main_splitter = wx.SplitterWindow(frame)
    splitter = wx.SplitterWindow(main_splitter)
    splitter.SplitVertically(wx.Panel(splitter), wx.Panel(splitter))
    panel = DummyListPanel()
    log_console = wx.TextCtrl(main_splitter)

    log_console.Hide()
    main_splitter.Initialize(splitter)
    frame.SetSize((800, 600))
    splitter.SetSashPosition(240)
    cfg.save_layout(frame, splitter, main_splitter, panel)

    # Restore layout into a new frame without calling Show()
    new_frame = wx.Frame(None)
    new_main_splitter = wx.SplitterWindow(new_frame)
    new_splitter = wx.SplitterWindow(new_main_splitter)
    new_splitter.SplitVertically(wx.Panel(new_splitter), wx.Panel(new_splitter))
    new_panel = DummyListPanel()
    new_log = wx.TextCtrl(new_main_splitter)

    cfg.restore_layout(new_frame, new_splitter, new_main_splitter, new_panel, new_log)

    assert new_splitter.GetSashPosition() == 240
