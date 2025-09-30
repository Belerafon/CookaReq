import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.mcp.client import MCPClient
from app.settings import MCPSettings

pytestmark = pytest.mark.unit


def _make_client(tmp_path: Path) -> MCPClient:
    settings = MCPSettings(base_path=str(tmp_path))
    return MCPClient(settings, confirm=lambda _: True)


def test_call_tool_forwards_arguments_without_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client(tmp_path)
    captured: dict[str, Any] = {}

    def _respond(*_, json_body=None, **__):
        captured["json_body"] = json_body

        class _Response:
            status_code = 400
            headers: dict[str, str] = {}
            text = json.dumps(
                {"error": {"code": "VALIDATION_ERROR", "message": "invalid"}}
            )

        return _Response()

    monkeypatch.setattr(client, "_request_sync", _respond)

    result = client.call_tool("create_requirement", {"prefix": "SYS"})

    assert result["ok"] is False
    assert result["error"]["code"] == "VALIDATION_ERROR"
    body = captured.get("json_body")
    assert body is not None
    assert body["name"] == "create_requirement"
    assert body["arguments"] == {"prefix": "SYS"}


def test_call_tool_async_forwards_arguments_without_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client(tmp_path)
    captured: dict[str, Any] = {}

    async def _respond(*_, json_body=None, **__):
        captured["json_body"] = json_body

        class _Response:
            status_code = 400
            headers: dict[str, str] = {}
            text = json.dumps(
                {"error": {"code": "VALIDATION_ERROR", "message": "invalid"}}
            )

        return _Response()

    monkeypatch.setattr(client, "_request_async", _respond)

    async def _invoke() -> None:
        result = await client.call_tool_async("create_requirement", {"prefix": "SYS"})
        assert result["ok"] is False

    asyncio.run(_invoke())

    body = captured.get("json_body")
    assert body is not None
    assert body["name"] == "create_requirement"
    assert body["arguments"] == {"prefix": "SYS"}
