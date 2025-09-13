import pytest


def test_available_translations_contains_locales():
    wx = pytest.importorskip("wx")
    from app.ui.settings_dialog import available_translations

    langs = available_translations()
    codes = {code for code, _ in langs}
    # english is default, russian is provided in repo
    assert {"en", "ru"}.issubset(codes)


def test_settings_dialog_returns_language():
    wx = pytest.importorskip("wx")
    _app = wx.App()
    from app.ui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(
        None,
        open_last=True,
        remember_sort=False,
        language="ru",
        api_base="http://api",
        model="gpt-test",
        api_key="key",
        timeout=30,
        host="127.0.0.1",
        port=8000,
        base_path="/tmp",
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
        30,
        "127.0.0.1",
        8000,
        "/tmp",
        True,
        "abc",
    )
    dlg.Destroy()


def test_mcp_start_stop_server(monkeypatch):
    wx = pytest.importorskip("wx")
    _app = wx.App()
    from app.ui.settings_dialog import SettingsDialog
    import app.ui.settings_dialog as sd
    from app.mcp.controller import MCPStatus

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
            return MCPStatus.NOT_RUNNING

    fake = FakeMCP()
    monkeypatch.setattr("app.ui.settings_dialog.MCPController", lambda: fake)

    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        api_base="",
        model="",
        api_key="",
        timeout=60,
        host="localhost",
        port=8123,
        base_path="/tmp",
        require_token=False,
        token="",
    )

    import app.ui.settings_dialog as sd

    assert dlg._start_stop.GetLabel() == sd._("Start MCP")

    dlg._on_start_stop(wx.CommandEvent())
    assert fake.calls[0][0] == "start"
    settings = fake.calls[0][1]
    assert (settings.host, settings.port, settings.base_path, settings.require_token, settings.token) == (
        "localhost",
        8123,
        "/tmp",
        False,
        "",
    )
    assert dlg._start_stop.GetLabel() == sd._("Stop MCP")

    dlg._on_start_stop(wx.CommandEvent())
    assert fake.calls[-1] == ("stop",)
    assert dlg._start_stop.GetLabel() == sd._("Start MCP")

    dlg.Destroy()


def test_mcp_check_status(monkeypatch):
    wx = pytest.importorskip("wx")
    _app = wx.App()
    from app.ui.settings_dialog import SettingsDialog
    import app.ui.settings_dialog as sd
    from app.mcp.controller import MCPStatus

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
            return self.state

    dummy = DummyMCP()
    monkeypatch.setattr("app.ui.settings_dialog.MCPController", lambda: dummy)

    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        api_base="",
        model="",
        api_key="",
        timeout=60,
        host="localhost",
        port=8123,
        base_path="/tmp",
        require_token=True,
        token="abc",
    )

    dummy.state = MCPStatus.READY
    dlg._on_check(wx.CommandEvent())
    assert dlg._status.GetLabel() == sd._("ready")

    dummy.state = MCPStatus.ERROR
    dlg._on_check(wx.CommandEvent())
    assert dlg._status.GetLabel() == sd._("error")

    dummy.state = MCPStatus.NOT_RUNNING
    dlg._on_check(wx.CommandEvent())
    assert dlg._status.GetLabel() == sd._("not running")

    dlg.Destroy()


def test_llm_agent_checks(monkeypatch):
    wx = pytest.importorskip("wx")
    _app = wx.App()
    from app.ui.settings_dialog import SettingsDialog
    import app.ui.settings_dialog as sd

    class DummyLLM:
        def __init__(self, *, settings):
            self.settings = settings

        def check_llm(self):
            return {"ok": True}

    class DummyMCP:
        def __init__(self, *, settings):
            self.settings = settings

        def check_tools(self):
            return {"ok": True}

    monkeypatch.setattr("app.ui.settings_dialog.LLMClient", lambda *, settings: DummyLLM(settings=settings))
    monkeypatch.setattr(
        "app.ui.settings_dialog.MCPClient",
        lambda *, settings, confirm: DummyMCP(settings=settings),
    )

    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        api_base="http://api",
        model="gpt", 
        api_key="key",
        timeout=30,
        host="localhost",
        port=8000,
        base_path="/tmp",
        require_token=False,
        token="",
    )

    dlg._on_check_llm(wx.CommandEvent())
    assert dlg._llm_status.GetLabel() == sd._("ok")

    dlg._on_check_tools(wx.CommandEvent())
    assert dlg._tools_status.GetLabel() == sd._("ok")

    dlg.Destroy()
