"""Tests for mcp client."""

import json
import logging
from pathlib import Path

import pytest

from app.log import logger
from app.mcp.client import MCPClient, MCPNotReadyError
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


def test_ensure_ready_success(tmp_path: Path) -> None:
    port = 8136
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
        client.ensure_ready()
        assert client._last_ready_check is not None
        first_check = client._last_ready_check
        client.ensure_ready()
        assert client._last_ready_check == first_check
        assert client._last_ready_ok is True
    finally:
        stop_server()


def test_ensure_ready_reports_connection_errors(tmp_path: Path) -> None:
    port = 8137
    stop_server()
    settings = settings_with_mcp(
        "127.0.0.1",
        port,
        str(tmp_path),
        "",
        tmp_path=tmp_path,
        fmt="toml",
    )
    client = MCPClient(settings.mcp, confirm=lambda _m: True)
    with pytest.raises(MCPNotReadyError) as excinfo:
        client.ensure_ready(force=True)
    error = excinfo.value.error_payload
    assert error["code"] == "INTERNAL"
    assert "not reachable" in error["message"]


def test_ensure_ready_respects_authorization(tmp_path: Path) -> None:
    port = 8138
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
            require_token=True,
        )
        client = MCPClient(settings.mcp, confirm=lambda _m: True)
        with pytest.raises(MCPNotReadyError) as excinfo:
            client.ensure_ready(force=True)
        assert excinfo.value.error_payload["code"] == "UNAUTHORIZED"
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

    def fail_request(self, *args, **kwargs):  # pragma: no cover - helper
        raise AssertionError("HTTP request should not be issued")

    monkeypatch.setattr(MCPClient, "_request_sync", fail_request)

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

    class DummyResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.headers: dict[str, str] = {}
            self._text = "{}"

        @property
        def text(self) -> str:
            return self._text

    calls: list[tuple[str, str, dict[str, str] | None, dict[str, object] | None]] = []

    def fake_request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict | None = None,
    ) -> DummyResponse:  # pragma: no cover - helper
        calls.append((method, path, headers, json_body))
        return DummyResponse()

    monkeypatch.setattr(MCPClient, "_request_sync", fake_request)

    res = client.call_tool("delete_requirement", {})
    assert res == {"ok": True, "error": None, "result": {}}
    assert calls and calls[0][0] == "POST"
    assert ("CONFIRM", {"tool": "delete_requirement"}) in events
    assert any(e[0] == "CONFIRM_RESULT" for e in events)
