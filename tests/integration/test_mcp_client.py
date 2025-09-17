"""Tests for mcp client."""

import json
import logging
from pathlib import Path

import pytest

from app.log import logger
from app.mcp.client import MCPClient
from app.mcp.server import JsonlHandler, start_server, stop_server
from app.settings import MCPSettings
from tests.llm_utils import settings_with_mcp
from tests.mcp_utils import _wait_until_ready

pytestmark = pytest.mark.integration


def test_check_tools_success(tmp_path: Path) -> None:
    port = 8134
    stop_server()
    start_server(port=port, base_path=str(tmp_path))
    try:
        _wait_until_ready(port)
        settings = settings_with_mcp(
            "127.0.0.1",
            port,
            str(tmp_path),
            "",
            tmp_path=tmp_path,
            fmt="toml",
        )
        client = MCPClient(settings.mcp, confirm=lambda _m: True)
        log_file = tmp_path / "log.jsonl"
        handler = JsonlHandler(str(log_file))
        logger.addHandler(handler)
        prev_level = logger.level
        logger.setLevel(logging.INFO)
        try:
            result = client.check_tools()
        finally:
            logger.setLevel(prev_level)
            logger.removeHandler(handler)
        assert result == {"ok": True, "error": None}
        lines = log_file.read_text().splitlines()
        entries = [json.loads(line) for line in lines]
        call = next(e for e in entries if e.get("event") == "TOOL_CALL")
        res = next(e for e in entries if e.get("event") == "TOOL_RESULT")
        assert call["payload"]["params"]["token"] == "[REDACTED]"
        assert res["payload"]["ok"] is True
        assert "duration_ms" in res
    finally:
        stop_server()


def test_check_tools_unauthorized(tmp_path: Path) -> None:
    port = 8135
    stop_server()
    start_server(port=port, base_path=str(tmp_path), token="secret")
    try:
        _wait_until_ready(port)
        settings = settings_with_mcp(
            "127.0.0.1",
            port,
            str(tmp_path),
            "wrong",
            tmp_path=tmp_path,
        )
        client = MCPClient(settings.mcp, confirm=lambda _m: True)
        result = client.check_tools()
        assert result["ok"] is False
        assert result["error"]["code"] == "UNAUTHORIZED"
    finally:
        stop_server()


def test_call_tool_delete_requires_confirmation(monkeypatch) -> None:
    settings = MCPSettings(
        host="127.0.0.1",
        port=0,
        base_path="",
        require_token=False,
        token="",
    )

    called = {"msg": None}

    def confirm(msg: str) -> bool:
        called["msg"] = msg
        return False

    client = MCPClient(settings, confirm=confirm)

    class DummyConn:
        def __init__(self, *a, **k):  # pragma: no cover - should not be used
            raise AssertionError("HTTPConnection should not be created")

    monkeypatch.setattr("app.mcp.client.HTTPConnection", DummyConn)

    res = client.call_tool("delete_requirement", {"rid": "SYS1", "rev": 1})
    assert res["ok"] is False
    assert res["error"]["code"] == "CANCELLED"
    assert called["msg"] is not None


def test_call_tool_delete_confirm_yes(monkeypatch) -> None:
    settings = MCPSettings(
        host="127.0.0.1",
        port=0,
        base_path="",
        require_token=False,
        token="",
    )

    client = MCPClient(settings, confirm=lambda _m: True)

    events: list[tuple[str, dict | None]] = []

    def fake_log(
        event: str,
        payload=None,
        start_time=None,
    ) -> None:  # pragma: no cover - helper
        events.append((event, payload))

    monkeypatch.setattr("app.mcp.client.log_event", fake_log)

    class DummyResp:
        status = 200

        def read(self) -> bytes:
            return b"{}"

    class DummyConn:
        def __init__(self, *a, **k) -> None:
            self.requested = False

        def request(self, *a, **k) -> None:
            self.requested = True

        def getresponse(self) -> DummyResp:
            return DummyResp()

        def close(self) -> None:
            pass

    conns: list[DummyConn] = []

    def factory(*a, **k) -> DummyConn:  # pragma: no cover - helper
        conn = DummyConn()
        conns.append(conn)
        return conn

    monkeypatch.setattr("app.mcp.client.HTTPConnection", factory)

    res = client.call_tool("delete_requirement", {})
    assert res == {"ok": True, "error": None, "result": {}}
    assert conns and conns[0].requested is True
    assert ("CONFIRM", {"tool": "delete_requirement"}) in events
    assert any(e[0] == "CONFIRM_RESULT" for e in events)
