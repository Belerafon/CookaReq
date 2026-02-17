"""Tests for settings dialog."""

import pytest

from app.llm.constants import DEFAULT_LLM_TEMPERATURE, DEFAULT_MAX_CONTEXT_TOKENS
from app.mcp.controller import MCPCheckResult, MCPStatus

pytestmark = [pytest.mark.gui, pytest.mark.integration]


class IdleMCPController:
    """Stub MCP controller keeping buttons consistent during tests."""

    def __init__(self) -> None:
        self.state = MCPStatus.NOT_RUNNING
        self.running = False

    def is_running(self) -> bool:
        return self.running

    def start(
        self,
        _settings,
        *,
        max_context_tokens: int,
        token_model: str | None,
    ) -> None:
        del max_context_tokens, token_model
        self.running = True

    def stop(self):
        self.running = False

    def check(self, _settings):
        return MCPCheckResult(self.state, f"{self.state.value}")


@pytest.mark.gui_smoke
def test_available_translations_contains_locales():
    pytest.importorskip("wx")
    from app.ui.settings_dialog import available_translations

    langs = available_translations()
    codes = {code for code, _ in langs}
    # english is default, russian is provided in repo
    assert {"en", "ru"}.issubset(codes)


@pytest.mark.gui_smoke
def test_settings_dialog_returns_language(wx_app):
    pytest.importorskip("wx")
    from app.ui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(
        None,
        open_last=True,
        remember_sort=False,
        language="ru",
        base_url="http://api",
        model="gpt-test",
        message_format="openai-chat",
        api_key="key",
        max_retries=2,
        max_context_tokens=DEFAULT_MAX_CONTEXT_TOKENS,
        timeout_minutes=30,
        use_custom_temperature=True,
        temperature=1.0,
        stream=True,
        auto_start=True,
        host="127.0.0.1",
        port=59362,
        base_path="/tmp",
        documents_path="docs",
        documents_max_read_kb=12,
        log_dir="/logs",
        require_token=True,
        token="abc",
        mcp_controller_factory=lambda: IdleMCPController(),
    )
    values = dlg.get_values()
    assert values == (
        True,
        False,
        "ru",
        "http://api",
        "gpt-test",
        "openai-chat",
        "key",
        2,
        DEFAULT_MAX_CONTEXT_TOKENS,
        30,
        True,
        1.0,
        True,
        True,
        "127.0.0.1",
        59362,
        "/tmp",
        "docs",
        12,
        "/logs",
        True,
        "abc",
    )
    dlg.Destroy()



def test_settings_dialog_shows_config_path(wx_app):
    pytest.importorskip("wx")
    from app.ui.settings_dialog import SettingsDialog

    config_path = "/home/test/.cookareq/config.json"
    dlg = SettingsDialog(
        None,
        open_last=True,
        remember_sort=False,
        language="en",
        settings_path=config_path,
        base_url="http://api",
        model="gpt-test",
        message_format="openai-chat",
        api_key="",
        max_retries=1,
        max_context_tokens=DEFAULT_MAX_CONTEXT_TOKENS,
        timeout_minutes=30,
        use_custom_temperature=False,
        temperature=DEFAULT_LLM_TEMPERATURE,
        stream=False,
        auto_start=False,
        host="127.0.0.1",
        port=8123,
        base_path="/tmp",
        documents_path="docs",
        documents_max_read_kb=10,
        log_dir="",
        require_token=False,
        token="",
        mcp_controller_factory=lambda: IdleMCPController(),
    )

    assert dlg._settings_path.GetValue() == config_path
    assert dlg._copy_settings_path.IsEnabled()
    dlg.Destroy()

def test_mcp_start_stop_server(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.settings_dialog as sd
    from app.mcp.controller import MCPCheckResult, MCPStatus
    from app.ui.settings_dialog import SettingsDialog

    class FakeMCP:
        def __init__(self) -> None:
            self.calls: list[tuple] = []
            self.running = False

        def is_running(self) -> bool:
            return self.running

        def start(
            self,
            settings,
            *,
            max_context_tokens: int,
            token_model: str | None,
        ) -> None:
            self.calls.append(("start", settings, max_context_tokens, token_model))
            self.running = True

        def stop(self):
            self.calls.append(("stop",))
            self.running = False

        def check(self, settings):
            return MCPCheckResult(MCPStatus.NOT_RUNNING, "")

    fake = FakeMCP()

    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        base_url="",
        model="",
        message_format="openai-chat",
        api_key="",
        max_retries=3,
        max_context_tokens=DEFAULT_MAX_CONTEXT_TOKENS,
        timeout_minutes=60,
        use_custom_temperature=False,
        temperature=DEFAULT_LLM_TEMPERATURE,
        stream=False,
        auto_start=True,
        host="localhost",
        port=8123,
        base_path="/tmp",
        documents_path="manuals",
        documents_max_read_kb=24,
        log_dir="",
        require_token=False,
        token="",
        mcp_controller_factory=lambda: fake,
    )

    assert dlg._start.IsEnabled()
    assert not dlg._stop.IsEnabled()
    assert dlg._status.GetLabel() == f"{sd._('Status')}: {sd._('not running')}"

    dlg._on_start(wx.CommandEvent())
    action, settings, max_tokens, token_model = fake.calls[0]
    assert action == "start"
    assert (
        settings.host,
        settings.port,
        settings.base_path,
        settings.documents_path,
        settings.documents_max_read_kb,
        settings.log_dir,
        settings.require_token,
        settings.token,
    ) == ("localhost", 8123, "/tmp", "manuals", 24, None, False, "")
    assert max_tokens == DEFAULT_MAX_CONTEXT_TOKENS
    assert token_model == ""
    assert not dlg._start.IsEnabled()
    assert dlg._stop.IsEnabled()
    assert dlg._status.GetLabel() == f"{sd._('Status')}: {sd._('running')}"

    dlg._on_stop(wx.CommandEvent())
    assert fake.calls[-1] == ("stop",)
    assert dlg._start.IsEnabled()
    assert not dlg._stop.IsEnabled()
    assert dlg._status.GetLabel() == f"{sd._('Status')}: {sd._('not running')}"

    dlg.Destroy()


def test_mcp_check_status(wx_app, intercept_message_box):
    wx = pytest.importorskip("wx")
    import app.ui.settings_dialog as sd
    from app.mcp.controller import MCPCheckResult, MCPStatus
    from app.ui.settings_dialog import SettingsDialog

    class DummyMCP:
        def __init__(self):
            self.state = MCPStatus.READY

        def is_running(self):
            return False

        def start(
            self,
            settings,
            *,
            max_context_tokens: int,
            token_model: str | None,
        ) -> None:
            del settings, max_context_tokens, token_model

        def stop(self):
            pass

        def check(self, settings):
            return MCPCheckResult(self.state, f"{self.state.value}")

    dummy = DummyMCP()
    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        base_url="",
        model="",
        message_format="openai-chat",
        api_key="",
        max_retries=3,
        max_context_tokens=DEFAULT_MAX_CONTEXT_TOKENS,
        timeout_minutes=60,
        use_custom_temperature=False,
        temperature=DEFAULT_LLM_TEMPERATURE,
        stream=False,
        auto_start=True,
        host="localhost",
        port=8123,
        base_path="/tmp",
        documents_path="docs",
        documents_max_read_kb=10,
        log_dir="",
        require_token=True,
        token="abc",
        mcp_controller_factory=lambda: dummy,
    )

    dummy.state = MCPStatus.READY
    dlg._on_check(wx.CommandEvent())
    assert dlg._status.GetLabel() == f"{sd._('Status')}: {sd._('ready')}"
    msg, caption, _style = intercept_message_box[-1]
    assert msg.startswith(f"{sd._('Status')}: {sd._('ready')}")
    assert caption == sd._("Check MCP")

    dummy.state = MCPStatus.ERROR
    dlg._on_check(wx.CommandEvent())
    assert dlg._status.GetLabel() == f"{sd._('Status')}: {sd._('error')}"

    dummy.state = MCPStatus.NOT_RUNNING
    dlg._on_check(wx.CommandEvent())
    assert dlg._status.GetLabel() == f"{sd._('Status')}: {sd._('not running')}"

    dlg.Destroy()


def test_llm_agent_checks(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.settings_dialog as sd
    from app.ui.settings_dialog import SettingsDialog

    class DummyLLM:
        last_settings = None

        def __init__(self, *, settings):
            self.settings = settings
            DummyLLM.last_settings = settings

        def check_llm(self):
            return {"ok": True}

    class DummyMCP:
        def __init__(self, *, settings):
            self.settings = settings

        def check_tools(self):
            return {"ok": True, "error": None}

    monkeypatch.setattr(
        "app.ui.settings_dialog.LLMClient",
        lambda *, settings: DummyLLM(settings=settings),
    )
    monkeypatch.setattr(
        "app.ui.settings_dialog.MCPClient",
        lambda *, settings, confirm: DummyMCP(settings=settings),
    )

    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        base_url="http://api",
        model="gpt",
        message_format="openai-chat",
        api_key="key",
        max_retries=3,
        max_context_tokens=DEFAULT_MAX_CONTEXT_TOKENS,
        timeout_minutes=30,
        use_custom_temperature=False,
        temperature=DEFAULT_LLM_TEMPERATURE,
        stream=False,
        auto_start=True,
        host="localhost",
        port=59362,
        base_path="/tmp",
        documents_path="share",
        documents_max_read_kb=10,
        log_dir="",
        require_token=False,
        token="",
        mcp_controller_factory=lambda: IdleMCPController(),
    )

    dlg._on_check_llm(wx.CommandEvent())
    assert dlg._llm_status.GetLabel() == sd._("ok")

    dlg._on_check_tools(wx.CommandEvent())
    assert dlg._tools_status.GetLabel() == sd._("ok")

    dlg.Destroy()


def test_llm_agent_check_failure_logs(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.settings_dialog as sd
    from app.ui.settings_dialog import SettingsDialog

    messages: list[str] = []

    def fake_warning(message, *args, **kwargs):
        if args:
            message = message % args
        messages.append(str(message))

    monkeypatch.setattr(sd.logger, "warning", fake_warning)

    class DummyLLM:
        def __init__(self, *, settings):
            self.settings = settings

        def check_llm(self):
            return {
                "ok": False,
                "error": {"type": "VALIDATION_ERROR", "message": "invalid"},
            }

    monkeypatch.setattr(
        "app.ui.settings_dialog.LLMClient",
        lambda *, settings: DummyLLM(settings=settings),
    )

    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        base_url="http://api",
        model="gpt",
        message_format="openai-chat",
        api_key="key",
        max_retries=3,
        max_context_tokens=DEFAULT_MAX_CONTEXT_TOKENS,
        timeout_minutes=30,
        use_custom_temperature=False,
        temperature=DEFAULT_LLM_TEMPERATURE,
        stream=False,
        auto_start=True,
        host="localhost",
        port=59362,
        base_path="/tmp",
        documents_path="share",
        documents_max_read_kb=10,
        log_dir="",
        require_token=False,
        token="",
        mcp_controller_factory=lambda: IdleMCPController(),
    )

    dlg._on_check_llm(wx.CommandEvent())
    assert dlg._llm_status.GetLabel() == sd._("error")
    tooltip = dlg._llm_status.GetToolTip()
    assert tooltip is not None
    assert tooltip.GetTip() == "VALIDATION_ERROR: invalid"
    assert messages and "invalid" in messages[0]
    assert "Check LLM" in messages[0]

    dlg.Destroy()


def test_settings_help_buttons(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    from app.ui import helpers
    from app.ui.settings_dialog import LLM_HELP, MCP_HELP, SettingsDialog

    shown: list[tuple[wx.Window | None, wx.Window | None, str]] = []

    def _fake_show_help(parent, msg, *, anchor=None, **_kwargs):
        shown.append((parent, anchor, msg))

    monkeypatch.setattr(helpers, "show_help", _fake_show_help)

    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        base_url="",
        model="",
        message_format="openai-chat",
        api_key="",
        max_retries=3,
        max_context_tokens=DEFAULT_MAX_CONTEXT_TOKENS,
        timeout_minutes=10,
        use_custom_temperature=False,
        temperature=DEFAULT_LLM_TEMPERATURE,
        stream=False,
        auto_start=True,
        host="localhost",
        port=8000,
        base_path="/tmp",
        documents_path="share",
        documents_max_read_kb=10,
        log_dir="",
        require_token=False,
        token="",
        mcp_controller_factory=lambda: IdleMCPController(),
    )

    base_btn = next(
        item.GetWindow()
        for item in dlg._base_url.GetContainingSizer().GetChildren()
        if isinstance(item.GetWindow(), wx.Button)
    )
    base_btn.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId))
    assert shown[-1] == (dlg, base_btn, LLM_HELP["base_url"])

    host_btn = next(
        item.GetWindow()
        for item in dlg._host.GetContainingSizer().GetChildren()
        if isinstance(item.GetWindow(), wx.Button)
    )
    host_btn.GetEventHandler().ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId))
    assert shown[-1] == (dlg, host_btn, MCP_HELP["host"])

    dlg.Destroy()


def test_documents_hint_tracks_filesystem(wx_app, tmp_path):
    wx = pytest.importorskip("wx")
    from app.ui.settings_dialog import SettingsDialog

    base_dir = tmp_path
    docs_dir = base_dir / "docs"
    docs_dir.mkdir()

    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        base_url="http://api",
        model="gpt-test",
        message_format="openai-chat",
        api_key="",
        max_retries=3,
        max_context_tokens=DEFAULT_MAX_CONTEXT_TOKENS,
        timeout_minutes=10,
        use_custom_temperature=False,
        temperature=DEFAULT_LLM_TEMPERATURE,
        stream=False,
        auto_start=True,
        host="localhost",
        port=8123,
        base_path=str(base_dir),
        documents_path="docs",
        documents_max_read_kb=10,
        log_dir="",
        require_token=False,
        token="",
        mcp_controller_factory=lambda: IdleMCPController(),
    )

    wx.YieldIfNeeded()
    hint = dlg._documents_hint
    expected_path = str(docs_dir.resolve())
    assert (
        hint.GetLabel()
        == f"Documentation root: {expected_path} — default read limit: 10 KiB"
    )
    assert hint.GetForegroundColour() == wx.Colour(0, 128, 0)

    dlg._documents_path.SetValue("missing")
    wx.YieldIfNeeded()
    missing_path = str((base_dir / "missing").resolve())
    assert (
        hint.GetLabel()
        == f"Documentation root: {missing_path} (missing) — default read limit: 10 KiB"
    )
    assert hint.GetForegroundColour() == wx.Colour(178, 34, 34)

    dlg._documents_path.SetValue("")
    wx.YieldIfNeeded()
    assert "Documentation disabled" in hint.GetLabel()
    assert hint.GetLabel().endswith("default read limit: 10 KiB")
    assert (
        hint.GetForegroundColour() == dlg._documents_hint_default_colour
    )

    dlg.Destroy()


def test_documents_hint_supports_absolute_path(wx_app, tmp_path):
    wx = pytest.importorskip("wx")
    from app.ui.settings_dialog import SettingsDialog

    docs_dir = tmp_path / "absolute"
    docs_dir.mkdir()

    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        base_url="http://api",
        model="gpt-test",
        message_format="openai-chat",
        api_key="",
        max_retries=3,
        max_context_tokens=DEFAULT_MAX_CONTEXT_TOKENS,
        timeout_minutes=10,
        use_custom_temperature=False,
        temperature=DEFAULT_LLM_TEMPERATURE,
        stream=False,
        auto_start=True,
        host="localhost",
        port=8123,
        base_path=str(tmp_path / "requirements"),
        documents_path=str(docs_dir),
        documents_max_read_kb=10,
        log_dir="",
        require_token=False,
        token="",
        mcp_controller_factory=lambda: IdleMCPController(),
    )

    wx.YieldIfNeeded()
    hint = dlg._documents_hint
    absolute_text = str(docs_dir)
    assert (
        hint.GetLabel()
        == f"Documentation root: {absolute_text} — default read limit: 10 KiB"
    )
    assert hint.GetForegroundColour() == wx.Colour(0, 128, 0)

    dlg._documents_path.SetValue(str(docs_dir / "missing"))
    wx.YieldIfNeeded()
    missing_abs = str(docs_dir / "missing")
    assert (
        hint.GetLabel()
        == f"Documentation root: {missing_abs} (missing) — default read limit: 10 KiB"
    )
    assert hint.GetForegroundColour() == wx.Colour(178, 34, 34)

    dlg.Destroy()
