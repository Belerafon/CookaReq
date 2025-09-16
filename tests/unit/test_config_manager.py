"""Tests for config manager."""

import pytest

from app.config import ConfigManager, DEFAULT_LIST_COLUMNS
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


def _const(value):
    def factory(_tmp_path):
        if isinstance(value, list):
            return list(value)
        return value

    return factory


def _list_columns_factory(_tmp_path):
    return ["id", "title"]


def _recent_dirs_factory(tmp_path):
    return [str(tmp_path / "a"), str(tmp_path / "b")]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("list_columns", DEFAULT_LIST_COLUMNS),
        ("recent_dirs", []),
        ("auto_open_last", False),
        ("remember_sort", False),
        ("language", None),
        ("mcp_auto_start", True),
        ("mcp_port", 59362),
        ("llm_max_output_tokens", None),
        ("sort_column", -1),
        ("sort_ascending", True),
        ("log_shown", False),
        ("win_w", 800),
    ],
)
def test_schema_default_values(tmp_path, wx_app, name, expected):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    assert cfg.get_value(name) == expected


@pytest.mark.parametrize(
    ("name", "value_factory", "expected_factory"),
    [
        pytest.param("list_columns", _list_columns_factory, _list_columns_factory, id="list_columns"),
        pytest.param("recent_dirs", _recent_dirs_factory, _recent_dirs_factory, id="recent_dirs"),
        pytest.param("auto_open_last", _const(True), _const(True), id="auto_open_last"),
        pytest.param("remember_sort", _const(True), _const(True), id="remember_sort"),
        pytest.param("language", _const("fr"), _const("fr"), id="language-set"),
        pytest.param("language", _const(None), _const(None), id="language-none"),
        pytest.param("mcp_auto_start", _const(False), _const(False), id="mcp_auto_start"),
        pytest.param("mcp_host", _const("10.0.0.1"), _const("10.0.0.1"), id="mcp_host"),
        pytest.param("mcp_port", _const(6543), _const(6543), id="mcp_port"),
        pytest.param("mcp_require_token", _const(True), _const(True), id="mcp_require_token"),
        pytest.param("mcp_token", _const("secret"), _const("secret"), id="mcp_token"),
        pytest.param("llm_base_url", _const("http://api"), _const("http://api"), id="llm_base_url"),
        pytest.param("llm_model", _const("model"), _const("model"), id="llm_model"),
        pytest.param("llm_api_key", _const("secret"), _const("secret"), id="llm_api_key"),
        pytest.param("llm_api_key", _const(None), _const(None), id="llm_api_key-none"),
        pytest.param("llm_max_retries", _const(7), _const(7), id="llm_max_retries"),
        pytest.param("llm_max_output_tokens", _const(128), _const(128), id="llm_max_output_tokens"),
        pytest.param("llm_max_output_tokens", _const(None), _const(None), id="llm_max_output_tokens-none"),
        pytest.param("llm_timeout_minutes", _const(12), _const(12), id="llm_timeout"),
        pytest.param("llm_stream", _const(True), _const(True), id="llm_stream"),
        pytest.param("sort_column", _const(5), _const(5), id="sort_column"),
        pytest.param("sort_ascending", _const(False), _const(False), id="sort_ascending"),
        pytest.param("log_sash", _const(512), _const(512), id="log_sash"),
        pytest.param("log_shown", _const(True), _const(True), id="log_shown"),
        pytest.param("win_w", _const(1024), _const(1024), id="win_w"),
    ],
)
def test_schema_round_trip(tmp_path, wx_app, name, value_factory, expected_factory):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    value = value_factory(tmp_path)
    cfg.set_value(name, value)
    cfg.flush()

    assert cfg.get_value(name) == expected_factory(tmp_path)


def test_schema_legacy_llm_base(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    cfg.write("llm_api_base", "http://legacy")
    cfg.flush()

    assert cfg.get_value("llm_base_url") == "http://legacy"


def test_schema_override_default(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    assert cfg.get_value("log_sash", default=123) == 123


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
    assert cfg.read_bool("log_shown") is log_shown

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
        mcp=MCPSettings(
            auto_start=False,
            host="1.2.3.4",
            port=9999,
            base_path="/m",
            require_token=True,
            token="t",
        ),
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
    assert cfg.read_int("sort_column") == 3
    assert cfg.read_bool("sort_ascending") is False


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
