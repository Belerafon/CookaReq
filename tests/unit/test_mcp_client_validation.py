import asyncio
import json
from pathlib import Path

import pytest

from app.llm.validation import ToolValidationError
from app.mcp.client import MCPClient
from app.settings import MCPSettings

pytestmark = pytest.mark.unit


def _make_client(tmp_path: Path) -> MCPClient:
    settings = MCPSettings(base_path=str(tmp_path))
    return MCPClient(settings, confirm=lambda _: True)


def test_call_tool_validates_known_tool_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client(tmp_path)
    monkeypatch.setattr(
        client,
        "_request_sync",
        lambda *a, **k: pytest.fail("unexpected HTTP request"),
    )

    with pytest.raises(ToolValidationError) as exc:
        client.call_tool("create_requirement", {"prefix": "SYS"})

    calls = getattr(exc.value, "llm_tool_calls", None)
    assert calls
    first_call = calls[0]
    assert first_call["function"]["name"] == "create_requirement"
    arguments = json.loads(first_call["function"]["arguments"])
    assert arguments["prefix"] == "SYS"


def test_call_tool_async_validates_before_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_client(tmp_path)

    async def _fail(*a, **k):
        pytest.fail("unexpected async HTTP request")

    monkeypatch.setattr(client, "_request_async", _fail)

    async def _invoke() -> None:
        with pytest.raises(ToolValidationError) as exc:
            await client.call_tool_async("create_requirement", {"prefix": "SYS"})
        calls = getattr(exc.value, "llm_tool_calls", None)
        assert calls
        assert calls[0]["function"]["name"] == "create_requirement"

    asyncio.run(_invoke())
