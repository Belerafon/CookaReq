"""Tests for config manager."""

import logging

import pytest

from app.columns import default_column_width
from app.config import ConfigManager, _FIRST_RUN_COLUMN_PRIORITY
from app.llm.constants import (
    DEFAULT_LLM_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_MAX_CONTEXT_TOKENS,
    MIN_MAX_CONTEXT_TOKENS,
)
from app.settings import (
    AppSettings,
    DEFAULT_LIST_COLUMNS,
    DEFAULT_DOCUMENT_MAX_READ_KB,
    LLMSettings,
    MCPSettings,
    UISettings,
    default_requirements_path,
)

pytestmark = pytest.mark.unit


def _expected_first_run_order(columns: list[str]) -> list[str]:
    order: list[str] = []
    seen: set[str] = set()

    def _add(field: str) -> None:
        if field not in seen:
            order.append(field)
            seen.add(field)

    for field in _FIRST_RUN_COLUMN_PRIORITY:
        if field == "title":
            _add("title")
            continue
        if field in columns:
            _add(field)
    for field in columns:
        _add(field)
    return order


def _expected_physical_fields(columns: list[str]) -> list[str]:
    fields: list[str] = []
    if "labels" in columns:
        fields.append("labels")
    fields.append("title")
    fields.extend(field for field in columns if field != "labels")
    return fields


def test_first_run_populates_column_defaults(tmp_path, wx_app):
    cfg_path = tmp_path / "first-run.json"
    cfg = ConfigManager(app_name="TestApp", path=cfg_path)

    columns = cfg.get_columns()
    expected_order = _expected_first_run_order(columns)

    assert columns == DEFAULT_LIST_COLUMNS
    assert cfg.get_column_order() == expected_order
    assert cfg.get_column_order()[:5] == [
        "id",
        "title",
        "source",
        "status",
        "labels",
    ]

    for index, field in enumerate(_expected_physical_fields(columns)):
        assert cfg.get_column_width(index, default=-1) == default_column_width(field)


def test_get_column_order_normalises_missing_priority_fields(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "normalize.json")
    cfg._raw["col_order"] = ["id", "status", "labels", "priority", "priority"]

    order = cfg.get_column_order()

    assert order[:5] == ["id", "title", "source", "status", "labels"]
    assert order[-3:] == ["priority", "type", "owner"]

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
        ("last_documents", {}),
        ("auto_open_last", False),
        ("remember_sort", False),
        ("language", None),
        ("mcp_auto_start", True),
        ("mcp_base_path", default_requirements_path()),
        ("mcp_documents_path", "share"),
        ("mcp_documents_max_read_kb", DEFAULT_DOCUMENT_MAX_READ_KB),
        ("mcp_port", 59362),
        ("llm_max_context_tokens", DEFAULT_MAX_CONTEXT_TOKENS),
        ("llm_format", "openai-chat"),
        ("sort_column", -1),
        ("sort_ascending", True),
        ("log_sash", 300),
        ("log_level", logging.INFO),
        ("log_shown", False),
        ("agent_chat_sash", 500),
        ("agent_chat_shown", False),
        ("agent_history_sash", 200),
        ("agent_confirm_mode", "prompt"),
        ("win_w", 1500),
        ("win_x", 100),
        ("win_y", 50),
        ("editor_sash_pos", 932),
        ("editor_shown", True),
        ("doc_tree_collapsed", False),
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
        pytest.param("last_documents", _const({"/tmp": "DOC"}), _const({"/tmp": "DOC"}), id="last_documents"),
        pytest.param("auto_open_last", _const(True), _const(True), id="auto_open_last"),
        pytest.param("remember_sort", _const(True), _const(True), id="remember_sort"),
        pytest.param("language", _const("fr"), _const("fr"), id="language-set"),
        pytest.param("language", _const(None), _const(None), id="language-none"),
        pytest.param("mcp_auto_start", _const(False), _const(False), id="mcp_auto_start"),
        pytest.param("mcp_host", _const("10.0.0.1"), _const("10.0.0.1"), id="mcp_host"),
        pytest.param("mcp_port", _const(6543), _const(6543), id="mcp_port"),
        pytest.param(
            "mcp_documents_path",
            _const("docs"),
            _const("docs"),
            id="mcp_documents_path",
        ),
        pytest.param(
            "mcp_documents_max_read_kb",
            _const(32),
            _const(32),
            id="mcp_documents_max_read_kb",
        ),
        pytest.param("mcp_require_token", _const(True), _const(True), id="mcp_require_token"),
        pytest.param("mcp_token", _const("secret"), _const("secret"), id="mcp_token"),
        pytest.param("llm_base_url", _const("http://api"), _const("http://api"), id="llm_base_url"),
        pytest.param("llm_model", _const("model"), _const("model"), id="llm_model"),
        pytest.param("llm_format", _const("harmony"), _const("harmony"), id="llm_format"),
        pytest.param("llm_api_key", _const("secret"), _const("secret"), id="llm_api_key"),
        pytest.param("llm_api_key", _const(None), _const(None), id="llm_api_key-none"),
        pytest.param("llm_max_retries", _const(7), _const(7), id="llm_max_retries"),
        pytest.param(
            "llm_max_context_tokens",
            _const(DEFAULT_MAX_CONTEXT_TOKENS + 2048),
            _const(DEFAULT_MAX_CONTEXT_TOKENS + 2048),
            id="llm_max_context_tokens",
        ),
        pytest.param("llm_timeout_minutes", _const(12), _const(12), id="llm_timeout"),
        pytest.param("llm_stream", _const(True), _const(True), id="llm_stream"),
        pytest.param("sort_column", _const(5), _const(5), id="sort_column"),
        pytest.param("sort_ascending", _const(False), _const(False), id="sort_ascending"),
        pytest.param("log_sash", _const(512), _const(512), id="log_sash"),
        pytest.param("log_level", _const(logging.ERROR), _const(logging.ERROR), id="log_level"),
        pytest.param("log_shown", _const(True), _const(True), id="log_shown"),
        pytest.param("agent_chat_shown", _const(True), _const(True), id="agent_chat_shown"),
        pytest.param("agent_chat_sash", _const(360), _const(360), id="agent_chat_sash"),
        pytest.param("agent_history_sash", _const(280), _const(280), id="agent_history_sash"),
        pytest.param("agent_confirm_mode", _const("never"), _const("never"), id="agent_confirm_mode"),
        pytest.param("win_w", _const(1024), _const(1024), id="win_w"),
        pytest.param("win_x", _const(12), _const(12), id="win_x"),
        pytest.param("win_y", _const(34), _const(34), id="win_y"),
        pytest.param("editor_sash_pos", _const(456), _const(456), id="editor_sash_pos"),
        pytest.param("editor_shown", _const(False), _const(False), id="editor_shown"),
        pytest.param("doc_tree_collapsed", _const(True), _const(True), id="doc_tree_collapsed"),
    ],
)
def test_schema_round_trip(tmp_path, wx_app, name, value_factory, expected_factory):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    value = value_factory(tmp_path)
    cfg.set_value(name, value)
    cfg.flush()

    assert cfg.get_value(name) == expected_factory(tmp_path)


def test_set_columns_sanitizes_invalid_and_duplicates(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    cfg.set_columns(["id", "bogus", "derived_from", "id"])

    assert cfg.get_columns() == ["id", "derived_from"]


def test_get_columns_filters_unknown_entries(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    cfg.set_value("list_columns", ["invalid", "labels", "id", "labels"])

    assert cfg.get_columns() == ["labels", "id"]


def test_set_last_document_persists_selection(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")
    directory = tmp_path / "project"
    directory.mkdir()

    cfg.set_last_document(directory, "DOC-1")

    assert cfg.get_last_document(directory) == "DOC-1"
    reloaded = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")
    assert reloaded.get_last_document(directory) == "DOC-1"
    assert reloaded.get_last_documents() == {str(directory.resolve()): "DOC-1"}


def test_last_document_clearing_removes_mapping(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")
    directory = tmp_path / "project"
    directory.mkdir()
    cfg.set_last_document(directory, "DOC-2")

    cfg.clear_last_document(directory)

    assert cfg.get_last_document(directory) is None
    reloaded = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")
    assert reloaded.get_last_documents() == {}


def test_last_document_normalises_paths(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")
    directory = tmp_path / "project"
    directory.mkdir()
    alias = directory / "."

    cfg.set_last_document(alias, "DOC-3")

    assert cfg.get_last_document(directory) == "DOC-3"
    assert cfg.get_last_document(str(directory)) == "DOC-3"


def test_schema_override_default(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    assert cfg.get_value("log_sash", default=123) == 123


def test_default_config_persists_within_test(wx_app):
    cfg_a = ConfigManager(app_name="PyTestCookaReq")
    cfg_a.set_language("fr")

    cfg_b = ConfigManager(app_name="PyTestCookaReq")
    assert cfg_b.get_language() == "fr"

    cfg_c = ConfigManager(app_name="OtherApp")
    assert cfg_c.get_language() is None


@pytest.mark.parametrize("log_shown", [True, False])
def test_save_and_restore_layout(tmp_path, log_shown, wx_app):
    wx = pytest.importorskip("wx")
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    frame = wx.Frame(None)
    main_splitter = wx.SplitterWindow(frame)
    doc_splitter = wx.SplitterWindow(main_splitter)
    editor_splitter = wx.SplitterWindow(doc_splitter)
    editor_splitter.SplitVertically(wx.Panel(editor_splitter), wx.Panel(editor_splitter))
    doc_splitter.SplitVertically(wx.Panel(doc_splitter), editor_splitter)
    panel = DummyListPanel()
    log_console = wx.TextCtrl(main_splitter)

    if log_shown:
        log_console.Show()
        main_splitter.SplitHorizontally(doc_splitter, log_console, 180)
    else:
        log_console.Hide()
        main_splitter.Initialize(doc_splitter)

    frame.SetSize((900, 700))
    frame.SetPosition((10, 20))
    doc_splitter.SetSashPosition(222)
    editor_splitter.SetSashPosition(333)

    cfg.save_layout(
        frame,
        doc_splitter,
        main_splitter,
        panel,
        editor_splitter=editor_splitter,
    )

    assert panel.saved_widths and panel.saved_order
    assert cfg.get_value("log_shown") is log_shown

    new_frame = wx.Frame(None)
    new_main_splitter = wx.SplitterWindow(new_frame)
    new_doc_splitter = wx.SplitterWindow(new_main_splitter)
    new_editor_splitter = wx.SplitterWindow(new_doc_splitter)
    new_editor_splitter.SplitVertically(wx.Panel(new_editor_splitter), wx.Panel(new_editor_splitter))
    new_doc_splitter.SplitVertically(wx.Panel(new_doc_splitter), new_editor_splitter)
    new_panel = DummyListPanel()
    new_log = wx.TextCtrl(new_main_splitter)
    new_frame.Show()

    cfg.restore_layout(
        new_frame,
        new_doc_splitter,
        new_main_splitter,
        new_panel,
        new_log,
        editor_splitter=new_editor_splitter,
    )

    assert new_frame.GetSize() == (900, 700)
    assert new_frame.GetPosition() == (10, 20)
    assert new_panel.loaded_widths and new_panel.loaded_order

    if log_shown:
        assert new_doc_splitter.GetSashPosition() == 222
        assert new_editor_splitter.GetSashPosition() == 333
        assert new_main_splitter.IsSplit()
        assert new_log.IsShown()
    else:
        assert new_doc_splitter.GetSashPosition() > 0
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
            max_context_tokens=DEFAULT_MAX_CONTEXT_TOKENS + 1024,
            timeout_minutes=42,
            stream=False,
        ),
        mcp=MCPSettings(
            auto_start=False,
            host="1.2.3.4",
            port=9999,
            base_path="/m",
            log_dir="/logs",
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
            log_level=logging.WARNING,
        ),
    )

    cfg.set_app_settings(app_settings)
    loaded = cfg.get_app_settings()
    assert loaded == app_settings


def test_get_mcp_settings_uses_default_requirements(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    settings = cfg.get_mcp_settings()

    assert settings.base_path == default_requirements_path()
    assert settings.documents_path == "share"
    assert settings.documents_max_read_kb == DEFAULT_DOCUMENT_MAX_READ_KB
    assert settings.log_dir is None


def test_app_settings_default_uses_sample_requirements():
    settings = AppSettings()

    assert settings.mcp.base_path == default_requirements_path()
    assert settings.mcp.documents_path == "share"
    assert settings.mcp.documents_max_read_kb == DEFAULT_DOCUMENT_MAX_READ_KB
    assert settings.mcp.log_dir is None
    assert settings.llm.base_url == DEFAULT_LLM_BASE_URL
    assert settings.llm.model == DEFAULT_LLM_MODEL


def test_get_llm_settings_normalises_context_zero(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    cfg.set_value("llm_max_context_tokens", 0)
    cfg.flush()

    settings = cfg.get_llm_settings()
    assert settings.max_context_tokens == DEFAULT_MAX_CONTEXT_TOKENS


def test_get_llm_settings_enforces_context_min(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    cfg.set_value("llm_max_context_tokens", 1024)
    cfg.flush()

    settings = cfg.get_llm_settings()
    assert settings.max_context_tokens == MIN_MAX_CONTEXT_TOKENS


def test_sort_settings_round_trip(tmp_path, wx_app):
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    cfg.set_sort_settings(3, False)
    assert cfg.get_sort_settings() == (3, False)
    assert cfg.get_value("sort_column") == 3
    assert cfg.get_value("sort_ascending") is False


def test_restore_layout_without_show(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    # Save initial layout with a known sash position
    frame = wx.Frame(None)
    main_splitter = wx.SplitterWindow(frame)
    doc_splitter = wx.SplitterWindow(main_splitter)
    editor_splitter = wx.SplitterWindow(doc_splitter)
    editor_splitter.SplitVertically(wx.Panel(editor_splitter), wx.Panel(editor_splitter))
    doc_splitter.SplitVertically(wx.Panel(doc_splitter), editor_splitter)
    panel = DummyListPanel()
    log_console = wx.TextCtrl(main_splitter)

    log_console.Hide()
    main_splitter.Initialize(doc_splitter)
    frame.SetSize((800, 600))
    doc_splitter.SetSashPosition(240)
    editor_splitter.SetSashPosition(350)
    cfg.save_layout(
        frame,
        doc_splitter,
        main_splitter,
        panel,
        editor_splitter=editor_splitter,
    )

    # Restore layout into a new frame without calling Show()
    new_frame = wx.Frame(None)
    new_main_splitter = wx.SplitterWindow(new_frame)
    new_doc_splitter = wx.SplitterWindow(new_main_splitter)
    new_editor_splitter = wx.SplitterWindow(new_doc_splitter)
    new_editor_splitter.SplitVertically(wx.Panel(new_editor_splitter), wx.Panel(new_editor_splitter))
    new_doc_splitter.SplitVertically(wx.Panel(new_doc_splitter), new_editor_splitter)
    new_panel = DummyListPanel()
    new_log = wx.TextCtrl(new_main_splitter)

    cfg.restore_layout(
        new_frame,
        new_doc_splitter,
        new_main_splitter,
        new_panel,
        new_log,
        editor_splitter=new_editor_splitter,
    )

    assert new_doc_splitter.GetSashPosition() == 240
    assert new_editor_splitter.GetSashPosition() == 350


def test_restore_layout_clamps_minimum(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg.ini")

    cfg.set_value("sash_pos", 0)
    cfg.set_value("editor_sash_pos", 0)
    cfg.flush()

    frame = wx.Frame(None)
    main_splitter = wx.SplitterWindow(frame)
    doc_splitter = wx.SplitterWindow(main_splitter)
    doc_splitter.SetMinimumPaneSize(180)
    editor_splitter = wx.SplitterWindow(doc_splitter)
    editor_splitter.SetMinimumPaneSize(200)
    editor_splitter.SplitVertically(wx.Panel(editor_splitter), wx.Panel(editor_splitter))
    doc_splitter.SplitVertically(wx.Panel(doc_splitter), editor_splitter)
    panel = DummyListPanel()
    log_console = wx.TextCtrl(main_splitter)
    log_console.Hide()
    main_splitter.Initialize(doc_splitter)

    cfg.restore_layout(
        frame,
        doc_splitter,
        main_splitter,
        panel,
        log_console,
        editor_splitter=editor_splitter,
    )

    assert doc_splitter.GetSashPosition() >= 180
    assert editor_splitter.GetSashPosition() >= 200

def test_save_layout_tracks_doc_tree_collapse(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg_doc.ini")

    frame = wx.Frame(None)
    main_splitter = wx.SplitterWindow(frame)
    doc_splitter = wx.SplitterWindow(main_splitter)
    editor_splitter = wx.SplitterWindow(doc_splitter)
    editor_splitter.SplitVertically(wx.Panel(editor_splitter), wx.Panel(editor_splitter))
    doc_splitter.SplitVertically(wx.Panel(doc_splitter), editor_splitter)
    panel = DummyListPanel()
    _log_console = wx.TextCtrl(main_splitter)

    frame.SetSize((820, 620))
    doc_splitter.SetSashPosition(250)

    cfg.save_layout(
        frame,
        doc_splitter,
        main_splitter,
        panel,
        editor_splitter=editor_splitter,
        doc_tree_shown=False,
        doc_tree_sash=250,
    )

    assert cfg.get_doc_tree_shown() is False
    assert cfg.get_doc_tree_sash(100) == 250


def test_save_layout_tracks_agent_history(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    cfg = ConfigManager(app_name="TestApp", path=tmp_path / "cfg_agent.ini")

    frame = wx.Frame(None)
    main_splitter = wx.SplitterWindow(frame)
    doc_splitter = wx.SplitterWindow(main_splitter)
    agent_splitter = wx.SplitterWindow(doc_splitter)
    doc_splitter.SplitVertically(wx.Panel(doc_splitter), agent_splitter)
    panel = DummyListPanel()

    frame.SetSize((900, 700))
    agent_splitter.SplitVertically(wx.Panel(agent_splitter), wx.Panel(agent_splitter), 360)

    cfg.save_layout(
        frame,
        doc_splitter,
        main_splitter,
        panel,
        agent_splitter=agent_splitter,
        agent_chat_sash=360,
        agent_history_sash=280,
    )

    assert cfg.get_agent_chat_shown() is True
    assert cfg.get_agent_chat_sash(10) == 360
    assert cfg.get_agent_history_sash(10) == 280

    cfg.set_agent_history_sash(300)
    assert cfg.get_agent_history_sash(0) == 300
