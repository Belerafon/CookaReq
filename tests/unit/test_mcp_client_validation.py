"""Validation tests for MCPClient argument handling."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.confirm import ConfirmDecision
from app.mcp.client import MCPClient
from app.llm.validation import ToolValidationError
from app.settings import MCPSettings

pytestmark = pytest.mark.unit


def _make_client(tmp_path: Path | None = None) -> MCPClient:
    settings_kwargs: dict[str, Any] = {}
    if tmp_path is not None:
        settings_kwargs["base_path"] = str(tmp_path)
    else:
        settings_kwargs["auto_start"] = False
    settings = MCPSettings(**settings_kwargs)

    def _confirm(_: str) -> bool:
        return True

    def _confirm_requirement_update(prompt) -> ConfirmDecision:
        return ConfirmDecision.YES

    return MCPClient(
        settings,
        confirm=_confirm,
        confirm_requirement_update=_confirm_requirement_update,
    )


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


def test_prepare_tool_arguments_rejects_non_mapping_arguments() -> None:
    client = _make_client()

    with pytest.raises(ToolValidationError) as excinfo:
        client._prepare_tool_arguments("update_requirement_field", "not-a-mapping")

    message = str(excinfo.value)
    assert "expected a JSON object" in message
    assert getattr(excinfo.value, "llm_message", "") == message
    tool_calls = getattr(excinfo.value, "llm_tool_calls", ())
    assert tool_calls
    first_call = tool_calls[0]
    assert first_call.get("name") == "update_requirement_field"
    assert first_call.get("arguments") == "not-a-mapping"


def test_call_tool_async_surfaces_validation_error_for_non_mapping_arguments() -> None:
    client = _make_client()

    with pytest.raises(ToolValidationError):
        asyncio.run(client.call_tool_async("update_requirement_field", "{}"))
