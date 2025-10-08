import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from app.agent import local_agent
from app.agent.local_agent import LocalAgent
from app.llm.types import LLMReasoningSegment, LLMResponse, LLMToolCall


class _StubLLM:
    async def check_llm_async(self) -> Mapping[str, Any]:
        return {"ok": True}

    async def respond_async(
        self,
        conversation: Sequence[Mapping[str, Any]] | None,
        *,
        cancellation: Any = None,
    ) -> LLMResponse:
        return LLMResponse(content="ok")


class _StubMCP:
    def __init__(self, result: Mapping[str, Any]) -> None:
        self._result = dict(result)
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    async def check_tools_async(self) -> Mapping[str, Any]:
        return {"ok": True}

    async def ensure_ready_async(self) -> None:
        return None

    async def call_tool_async(
        self, name: str, arguments: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.calls.append((name, dict(arguments)))
        return dict(self._result)


def _build_agent(result: Mapping[str, Any]) -> LocalAgent:
    return LocalAgent(llm=_StubLLM(), mcp=_StubMCP(result))


def test_log_step_emits_detailed_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = _build_agent({"ok": True, "result": {}})

    captured: list[tuple[str, Mapping[str, Any] | None]] = []

    monkeypatch.setattr(local_agent, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        local_agent,
        "log_debug_payload",
        lambda event, payload=None: captured.append((event, payload)),
    )

    response = LLMResponse(
        content="готово",
        tool_calls=(
            LLMToolCall(
                id="call-1",
                name="update_requirement_field",
                arguments={"rid": "DEMO14", "field": "title", "value": "Текст"},
            ),
        ),
        reasoning=(
            LLMReasoningSegment(type="reasoning", text="analyse"),
        ),
        request_messages=(
            {"role": "system", "content": "prompt"},
            {"role": "user", "content": "command"},
        ),
    )

    agent._log_step(1, response)

    detail = next(payload for event, payload in captured if event == "AGENT_STEP_DETAIL")
    tool_calls = detail["response"]["tool_calls"]
    assert tool_calls[0]["arguments"]["field"] == "title"
    assert detail["request_messages"][0]["role"] == "system"
    reasoning = detail["response"]["reasoning"]
    assert reasoning[0]["text"] == "analyse"


def test_execute_tool_calls_logs_full_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result_payload = {"ok": True, "result": {"rid": "DEMO14", "field": "title"}}
    agent = _build_agent(result_payload)

    captured: list[tuple[str, Mapping[str, Any] | None]] = []
    monkeypatch.setattr(local_agent, "log_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        local_agent,
        "log_debug_payload",
        lambda event, payload=None: captured.append((event, payload)),
    )

    tool_call = LLMToolCall(
        id="call-1",
        name="update_requirement_field",
        arguments={"rid": "DEMO14", "field": "title", "value": "Текст"},
    )

    messages, error_payload, successful = asyncio.run(
        agent._execute_tool_calls_core((tool_call,))
    )

    assert messages[0]["content"] != ""
    assert error_payload is None
    assert successful and successful[0]["ok"] is True

    call_detail = next(payload for event, payload in captured if event == "AGENT_TOOL_CALL_DETAIL")
    assert call_detail["arguments"]["rid"] == "DEMO14"

    result_detail = next(
        payload
        for event, payload in captured
        if event == "AGENT_TOOL_RESULT_DETAIL" and payload.get("ok")
    )
    assert result_detail["result"]["result"]["rid"] == "DEMO14"
