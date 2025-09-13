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
        host="127.0.0.1",
        port=8000,
        base_path="/tmp",
        require_token=True,
        token="abc",
    )
    values = dlg.get_values()
    assert values == (True, False, "ru", "127.0.0.1", 8000, "/tmp", True, "abc")
    dlg.Destroy()


def test_mcp_start_stop_server(monkeypatch):
    wx = pytest.importorskip("wx")
    _app = wx.App()
    from gettext import gettext as _
    from app.ui.settings_dialog import SettingsDialog

    state = {"running": False}
    calls: list[tuple] = []

    def fake_is_running():
        return state["running"]

    def fake_start_server(host, port, base_path, token):
        calls.append(("start", host, port, base_path, token))
        state["running"] = True

    def fake_stop_server():
        calls.append(("stop",))
        state["running"] = False

    monkeypatch.setattr("app.ui.settings_dialog.is_running", fake_is_running)
    monkeypatch.setattr("app.ui.settings_dialog.start_server", fake_start_server)
    monkeypatch.setattr("app.ui.settings_dialog.stop_server", fake_stop_server)

    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        host="localhost",
        port=8123,
        base_path="/tmp",
        require_token=False,
        token="",
    )

    assert dlg._start_stop.GetLabel() == _("Start MCP")

    dlg._on_start_stop(wx.CommandEvent())
    assert calls == [("start", "localhost", 8123, "/tmp", "")]
    assert dlg._start_stop.GetLabel() == _("Stop MCP")

    dlg._on_start_stop(wx.CommandEvent())
    assert calls[-1] == ("stop",)
    assert dlg._start_stop.GetLabel() == _("Start MCP")

    dlg.Destroy()


def test_mcp_check_status(monkeypatch):
    wx = pytest.importorskip("wx")
    _app = wx.App()
    from gettext import gettext as _
    from app.ui.settings_dialog import SettingsDialog

    requests: list[dict] = []

    class FakeResponse:
        def __init__(self, status: int) -> None:
            self.status = status

        def read(self) -> None:  # pragma: no cover - no data
            return None

    class FakeConnection:
        def __init__(self, host, port, timeout=2) -> None:
            self.host = host
            self.port = port
            self.timeout = timeout

        def request(self, method, path, headers=None):
            requests.append(headers or {})

        def getresponse(self):
            return FakeResponse(200)

        def close(self) -> None:  # pragma: no cover - nothing to close
            return None

    monkeypatch.setattr(
        "app.ui.settings_dialog.HTTPConnection",
        lambda host, port, timeout=2: FakeConnection(host, port, timeout),
    )

    dlg = SettingsDialog(
        None,
        open_last=False,
        remember_sort=False,
        language="en",
        host="localhost",
        port=8123,
        base_path="/tmp",
        require_token=True,
        token="abc",
    )

    dlg._on_check(wx.CommandEvent())
    assert dlg._status.GetLabel() == _("ready")
    assert requests[0]["Authorization"] == "Bearer abc"

    class BadConnection(FakeConnection):
        def getresponse(self):
            return FakeResponse(500)

    monkeypatch.setattr(
        "app.ui.settings_dialog.HTTPConnection",
        lambda host, port, timeout=2: BadConnection(host, port, timeout),
    )
    dlg._on_check(wx.CommandEvent())
    assert dlg._status.GetLabel() == _("error")

    def ErrorConnection(host, port, timeout=2):
        raise OSError("fail")

    monkeypatch.setattr("app.ui.settings_dialog.HTTPConnection", ErrorConnection)
    dlg._on_check(wx.CommandEvent())
    assert dlg._status.GetLabel() == _("not running")

    dlg.Destroy()
