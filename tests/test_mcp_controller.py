import pytest

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
        host="localhost", port=8123, base_path="/tmp", require_token=True, token="abc"
    )
    assert ctrl.check(settings) is MCPStatus.READY
    assert requests[0]["Authorization"] == "Bearer abc"

    class BadConnection(FakeConnection):
        def getresponse(self):
            return FakeResponse(500)

    monkeypatch.setattr(
        "app.mcp.controller.HTTPConnection",
        lambda host, port, timeout=2: BadConnection(host, port, timeout),
    )
    assert ctrl.check(settings) is MCPStatus.ERROR

    def ErrorConnection(host, port, timeout=2):
        raise OSError("fail")

    monkeypatch.setattr("app.mcp.controller.HTTPConnection", ErrorConnection)
    assert ctrl.check(settings) is MCPStatus.NOT_RUNNING


def test_controller_start_stop(monkeypatch):
    from app.mcp.controller import MCPController
    from app.settings import MCPSettings

    calls = []

    monkeypatch.setattr(
        "app.mcp.controller.start_server",
        lambda host, port, base_path, token: calls.append(("start", host, port, base_path, token)),
    )
    monkeypatch.setattr(
        "app.mcp.controller.stop_server", lambda: calls.append(("stop",))
    )

    ctrl = MCPController()
    settings = MCPSettings(host="localhost", port=8123, base_path="/tmp", token="")
    ctrl.start(settings)
    ctrl.stop()
    assert calls == [("start", "localhost", 8123, "/tmp", ""), ("stop",)]
