"""Tests for settings dialog."""

import pytest

pytestmark = [pytest.mark.gui, pytest.mark.integration]


def test_available_translations_contains_locales():
    pytest.importorskip("wx")
    from app.ui.settings_dialog import available_translations

    langs = available_translations()
    codes = {code for code, _ in langs}
    # english is default, russian is provided in repo
    assert {"en", "ru"}.issubset(codes)


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
        api_key="key",
        max_retries=2,
        timeout_minutes=30,
        stream=True,
        auto_start=True,
        host="127.0.0.1",
        port=59362,
        base_path="/tmp",
        log_dir="/logs",
        require_token=True,
        token="abc",
    )
    values = dlg.get_values()
    assert values == (
        True,
        False,
        "ru",
        "http://api",
        "gpt-test",
        "key",
        2,
        30,
        True,
        True,
        "127.0.0.1",
        59362,
        "/tmp",
        "/logs",
        True,
        "abc",
    )
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

        def start(self, settings):
            self.calls.append(("start", settings))
            self.running = True

        def stop(self):
            self.calls.append(("stop",))
            self.running = False

        def check(self, settings):
            return MCPCheckResult(MCPStatus.NOT_RUNNING, "")

    fake = FakeMCP()
    monkeypatch.setattr("app.ui.settings_dialog.MCPController", lambda: fake)

    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        base_url="",
        model="",
        api_key="",
        max_retries=3,
        timeout_minutes=60,
        stream=False,
        auto_start=True,
        host="localhost",
        port=8123,
        base_path="/tmp",
        log_dir="",
        require_token=False,
        token="",
    )

    assert dlg._start.IsEnabled()
    assert not dlg._stop.IsEnabled()
    assert dlg._status.GetLabel() == f"{sd._('Status')}: {sd._('not running')}"

    dlg._on_start(wx.CommandEvent())
    assert fake.calls[0][0] == "start"
    settings = fake.calls[0][1]
    assert (
        settings.host,
        settings.port,
        settings.base_path,
        settings.log_dir,
        settings.require_token,
        settings.token,
    ) == ("localhost", 8123, "/tmp", None, False, "")
    assert not dlg._start.IsEnabled()
    assert dlg._stop.IsEnabled()
    assert dlg._status.GetLabel() == f"{sd._('Status')}: {sd._('running')}"

    dlg._on_stop(wx.CommandEvent())
    assert fake.calls[-1] == ("stop",)
    assert dlg._start.IsEnabled()
    assert not dlg._stop.IsEnabled()
    assert dlg._status.GetLabel() == f"{sd._('Status')}: {sd._('not running')}"

    dlg.Destroy()


def test_mcp_check_status(monkeypatch, wx_app):
    wx = pytest.importorskip("wx")
    import app.ui.settings_dialog as sd
    from app.mcp.controller import MCPCheckResult, MCPStatus
    from app.ui.settings_dialog import SettingsDialog

    class DummyMCP:
        def __init__(self):
            self.state = MCPStatus.READY

        def is_running(self):
            return False

        def start(self, settings):
            pass

        def stop(self):
            pass

        def check(self, settings):
            return MCPCheckResult(self.state, f"{self.state.value}")

    dummy = DummyMCP()
    monkeypatch.setattr("app.ui.settings_dialog.MCPController", lambda: dummy)
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "wx.MessageBox",
        lambda msg, caption, *a, **k: messages.append((msg, caption)),
    )

    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        base_url="",
        model="",
        api_key="",
        max_retries=3,
        timeout_minutes=60,
        stream=False,
        auto_start=True,
        host="localhost",
        port=8123,
        base_path="/tmp",
        log_dir="",
        require_token=True,
        token="abc",
    )

    dummy.state = MCPStatus.READY
    dlg._on_check(wx.CommandEvent())
    assert dlg._status.GetLabel() == f"{sd._('Status')}: {sd._('ready')}"
    msg, caption = messages[-1]
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
        api_key="key",
        max_retries=3,
        timeout_minutes=30,
        stream=False,
        auto_start=True,
        host="localhost",
        port=59362,
        base_path="/tmp",
        log_dir="",
        require_token=False,
        token="",
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
        api_key="key",
        max_retries=3,
        timeout_minutes=30,
        stream=False,
        auto_start=True,
        host="localhost",
        port=59362,
        base_path="/tmp",
        log_dir="",
        require_token=False,
        token="",
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
        api_key="",
        max_retries=3,
        timeout_minutes=10,
        stream=False,
        auto_start=True,
        host="localhost",
        port=8000,
        base_path="/tmp",
        log_dir="",
        require_token=False,
        token="",
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
