import asyncio
import json
from typing import Any
from collections.abc import Mapping

from app.agent.local_agent import AgentLoopRunner, LocalAgent
from app.llm.types import LLMReasoningSegment, LLMResponse, LLMToolCall
from app.llm.validation import ToolValidationError


class DummyLLM:
    async def check_llm_async(self) -> Mapping[str, Any]:  # pragma: no cover - unused
        return {"ok": True}

    async def respond_async(self, conversation, *, cancellation=None) -> LLMResponse:
        return LLMResponse("done", ())


class DummyMCP:
    async def check_tools_async(self) -> Mapping[str, Any]:  # pragma: no cover - unused
        return {"ok": True}

    async def ensure_ready_async(self) -> None:  # pragma: no cover - unused
        return None

    async def call_tool_async(self, name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:  # pragma: no cover - unused
        return {"ok": True, "error": None}


def test_handle_tool_batch_returns_success(monkeypatch):
    agent = LocalAgent(llm=DummyLLM(), mcp=DummyMCP())

    runner = AgentLoopRunner(
        agent=agent,
        conversation=[],
        cancellation=None,
        on_tool_result=None,
        on_llm_step=None,
    )

    response = LLMResponse("Result", ())
    outcome = asyncio.run(runner.handle_tool_batch(response))

    assert outcome.final_result == {"ok": True, "error": None, "result": "Result"}
    assert runner.should_abort() is False
    assert runner._step == 1
    assert runner._conversation == [{"role": "assistant", "content": "Result"}]


def test_step_llm_handles_validation_error(monkeypatch):
    class RaisingLLM(DummyLLM):
        async def respond_async(self, conversation, *, cancellation=None) -> LLMResponse:
            exc = ToolValidationError("boom")
            exc.llm_message = "bad"
            raise exc

    agent = LocalAgent(llm=RaisingLLM(), mcp=DummyMCP())

    synthetic_response = LLMResponse("", ())
    synthetic_error = {"tool_name": "demo"}

    def fake_handle(self, exc, conversation, *, on_tool_result=None, on_llm_step=None):
        conversation.append({"role": "assistant", "content": "oops"})
        return synthetic_response, synthetic_error

    monkeypatch.setattr(LocalAgent, "_handle_tool_validation_error", fake_handle)

    runner = AgentLoopRunner(
        agent=agent,
        conversation=[],
        cancellation=None,
        on_tool_result=None,
        on_llm_step=None,
    )

    outcome = asyncio.run(runner.step_llm())

    assert outcome.tool_error is synthetic_error
    assert outcome.final_result is None
    assert runner._step == 1
    assert runner._conversation == [{"role": "assistant", "content": "oops"}]


def test_runner_aborts_after_consecutive_tool_errors(monkeypatch):
    class ToolLoopLLM(DummyLLM):
        call_index = 0

        async def respond_async(self, conversation, *, cancellation=None) -> LLMResponse:
            self.__class__.call_index += 1
            return LLMResponse(
                "",
                (
                    LLMToolCall(
                        id=f"call-{self.call_index}",
                        name="fail_tool",
                        arguments={},
                    ),
                ),
            )

    agent = LocalAgent(
        llm=ToolLoopLLM(),
        mcp=DummyMCP(),
        max_consecutive_tool_errors=2,
    )

    failure_payload = {
        "ok": False,
        "error": {"type": "Failure", "message": "boom"},
        "tool_name": "fail_tool",
        "tool_call_id": "call-1",
    }

    async def fake_execute(
        self,
        tool_calls,
        *,
        cancellation=None,
        on_tool_result=None,
    ):
        return (
            [
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "name": "fail_tool",
                    "content": "{}",
                }
            ],
            failure_payload,
            [],
        )

    monkeypatch.setattr(LocalAgent, "_execute_tool_calls_core", fake_execute)

    runner = AgentLoopRunner(
        agent=agent,
        conversation=[],
        cancellation=None,
        on_tool_result=None,
        on_llm_step=None,
    )

    result = asyncio.run(runner.run())

    assert result["ok"] is False
    assert result["agent_stop_reason"] == {
        "type": "consecutive_tool_errors",
        "count": 2,
        "max_consecutive_tool_errors": 2,
    }
    assert runner._consecutive_tool_errors == 2


def test_reasoning_segments_survive_tool_roundtrip(monkeypatch):
    class ToolReasoningLLM(DummyLLM):
        def __init__(self) -> None:
            self._call_index = 0

        async def respond_async(self, conversation, *, cancellation=None) -> LLMResponse:
            if self._call_index == 0:
                self._call_index += 1
                return LLMResponse(
                    "",
                    (
                        LLMToolCall(
                            id="call-1",
                            name="demo_tool",
                            arguments={},
                        ),
                    ),
                    reasoning=(
                        LLMReasoningSegment(
                            type="analysis",
                            text="gathering data",
                        ),
                    ),
                )
            self._call_index += 1
            return LLMResponse("final reply", ())

    agent = LocalAgent(llm=ToolReasoningLLM(), mcp=DummyMCP())

    async def fake_execute(
        self,
        tool_calls,
        *,
        cancellation=None,
        on_tool_result=None,
    ):
        return (
            [
                {
                    "role": "tool",
                    "tool_call_id": tool_calls[0].id,
                    "name": tool_calls[0].name,
                    "content": "{}",
                }
            ],
            None,
            [
                {
                    "ok": True,
                    "tool_name": tool_calls[0].name,
                }
            ],
        )

    monkeypatch.setattr(LocalAgent, "_execute_tool_calls_core", fake_execute)

    runner = AgentLoopRunner(
        agent=agent,
        conversation=[],
        cancellation=None,
        on_tool_result=None,
        on_llm_step=None,
    )

    result = asyncio.run(runner.run())

    assert result["result"] == "final reply"
    assert result["reasoning"] == [
        {"type": "analysis", "text": "gathering data"}
    ]


def test_validation_error_payloads_mirror_tool_execution():
    agent = LocalAgent(llm=DummyLLM(), mcp=DummyMCP())
    exc = ToolValidationError("invalid")
    exc.llm_message = "assistant reply"
    exc.llm_tool_calls = [
        {
            "id": "call-1",
            "function": {
                "name": "create_requirement",
                "arguments": json.dumps({"foo": 1}, ensure_ascii=False),
            },
        },
        {
            "function": {"name": "broken", "arguments": "not json"},
        },
    ]
    exc.llm_request_messages = (
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "assistant reply"},
    )

    recorded_payloads: list[Mapping[str, Any]] = []

    def recorder(payload: Mapping[str, Any]) -> None:
        recorded_payloads.append(dict(payload))

    conversation: list[Mapping[str, Any]] = []
    response, first_error = agent._handle_tool_validation_error(
        exc,
        conversation,
        on_tool_result=recorder,
    )

    assert response.content == "assistant reply"
    assert len(response.tool_calls) == 2
    assert len(recorded_payloads) == 2
    assert recorded_payloads[0] == dict(first_error)

    assert len(conversation) == 3
    assistant_message = conversation[0]
    assert assistant_message["role"] == "assistant"
    tool_calls = assistant_message["tool_calls"]
    assert tool_calls[0]["function"]["arguments"] == json.dumps(
        {"foo": 1}, ensure_ascii=False
    )
    assert tool_calls[1]["function"]["arguments"] == "not json"

    first_tool_message = json.loads(conversation[1]["content"])
    assert first_tool_message == recorded_payloads[0]
    second_tool_message = json.loads(conversation[2]["content"])
    assert second_tool_message == recorded_payloads[1]

    assert recorded_payloads[0]["tool_arguments"] == {"foo": 1}
    assert recorded_payloads[1]["tool_arguments"] == "not json"
