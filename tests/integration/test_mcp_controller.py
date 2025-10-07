"""Tests for mcp controller."""

import pytest

pytestmark = pytest.mark.integration


def test_controller_check(monkeypatch):
    from app.mcp.controller import MCPController, MCPStatus
    from app.settings import MCPSettings

    requests = []

    class FakeResponse:
        def __init__(self, status):
            self.status = status

        def read(self):
            return None

    class FakeConnection:
        def __init__(self, host, port, timeout=2):
            self.host = host
            self.port = port
            self.timeout = timeout

        def request(self, method, path, headers=None):
            requests.append(headers or {})

        def getresponse(self):
            return FakeResponse(200)

        def close(self):
            return None

    monkeypatch.setattr(
        "app.mcp.controller.HTTPConnection",
        lambda host, port, timeout=2: FakeConnection(host, port, timeout),
    )

    ctrl = MCPController()
    settings = MCPSettings(
        host="localhost",
        port=8123,
        base_path="/tmp",
        require_token=True,
        token="abc",
    )
    res = ctrl.check(settings)
    assert res.status is MCPStatus.READY
    assert "GET /health" in res.message and "200" in res.message
    assert requests[0]["Authorization"] == "Bearer abc"

    class BadConnection(FakeConnection):
        def getresponse(self):
            return FakeResponse(500)

    monkeypatch.setattr(
        "app.mcp.controller.HTTPConnection",
        lambda host, port, timeout=2: BadConnection(host, port, timeout),
    )
    res = ctrl.check(settings)
    assert res.status is MCPStatus.ERROR
    assert "500" in res.message

    def ErrorConnection(host, port, timeout=2):
        raise OSError("fail")

    monkeypatch.setattr("app.mcp.controller.HTTPConnection", ErrorConnection)
    res = ctrl.check(settings)
    assert res.status is MCPStatus.NOT_RUNNING
    assert "fail" in res.message


def test_controller_start_stop(monkeypatch):
    from app.mcp.controller import MCPController
    from app.settings import MCPSettings

    calls = []

    def fake_start(
        host,
        port,
        base_path,
        documents_path,
        token,
        *,
        log_dir=None,
    ) -> None:
        calls.append(
            ("start", host, port, base_path, documents_path, token, log_dir)
        )

    monkeypatch.setattr("app.mcp.controller.start_server", fake_start)
    monkeypatch.setattr(
        "app.mcp.controller.stop_server",
        lambda: calls.append(("stop",)),
    )

    ctrl = MCPController()
    settings = MCPSettings(host="localhost", port=8123, base_path="/tmp", token="")
    ctrl.start(settings)
    ctrl.stop()
    assert calls == [
        ("start", "localhost", 8123, "/tmp", settings.documents_path, "", None),
        ("stop",),
    ]
