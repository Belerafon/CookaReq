import asyncio
import json
from typing import Any
from collections.abc import Mapping

from app.agent.local_agent import AgentLoopRunner, LocalAgent, _AgentRunRecorder
from app.agent.run_contract import AgentRunPayload, ToolResultSnapshot
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
        return {"ok": True, "result": {}}


def _create_runner(agent: LocalAgent) -> AgentLoopRunner:
    recorder = _AgentRunRecorder(tool_schemas=None)
    return AgentLoopRunner(
        agent=agent,
        recorder=recorder,
        conversation=[],
        cancellation=None,
        on_tool_result=None,
        on_llm_step=None,
    )


def _run(coro):
    return asyncio.run(coro)


def test_runner_returns_success_without_tools():
    agent = LocalAgent(llm=DummyLLM(), mcp=DummyMCP())
    runner = _create_runner(agent)

    payload = _run(runner.run())

    assert isinstance(payload, AgentRunPayload)
    assert payload.ok is True
    assert payload.status == "succeeded"
    assert payload.result_text == "done"
    assert payload.tool_results == []
    assert len(payload.llm_trace.steps) == 1
    assert runner._step == 1
    assert runner._conversation == [{"role": "assistant", "content": "done"}]


def test_step_llm_handles_validation_error(monkeypatch):
    class RaisingLLM(DummyLLM):
        async def respond_async(self, conversation, *, cancellation=None) -> LLMResponse:
            exc = ToolValidationError("boom")
            exc.llm_message = "bad"
            raise exc

    agent = LocalAgent(llm=RaisingLLM(), mcp=DummyMCP())
    runner = _create_runner(agent)

    result = _run(runner._step_once())

    assert isinstance(result.tool_error, Mapping)
    assert result.final_payload is None
    assert runner._step == 1
    assert runner._conversation
    assert runner._conversation[0]["role"] == "assistant"
    assert runner._conversation[0]["content"] == "bad"


def test_validation_error_without_tool_calls_adds_placeholder():
    agent = LocalAgent(llm=DummyLLM(), mcp=DummyMCP())
    exc = ToolValidationError("broken")
    exc.llm_message = "assistant reply"

    runner = _create_runner(agent)

    iteration = _run(runner._handle_validation_error(exc))

    assert isinstance(iteration.tool_error, Mapping)
    assert iteration.tool_messages and len(iteration.tool_messages) == 1

    assert len(runner._conversation) == 2
    assistant_message, tool_message = runner._conversation
    assert assistant_message["role"] == "assistant"
    tool_calls = assistant_message.get("tool_calls")
    assert isinstance(tool_calls, list) and len(tool_calls) == 1
    placeholder_call = tool_calls[0]
    assert placeholder_call["function"]["name"] == "__tool_validation_error__"
    assert tool_message["role"] == "tool"
    assert tool_message["tool_call_id"] == placeholder_call["id"]

    payload = json.loads(tool_message["content"])
    assert payload["error"]["code"] == "VALIDATION_ERROR"
    assert payload["tool_call_id"] == placeholder_call["id"]


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

    async def fail_call(name: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        return {
            "ok": False,
            "error": {"code": "Failure", "message": "boom"},
        }

    monkeypatch.setattr(agent._mcp, "call_tool_async", fail_call)

    runner = _create_runner(agent)

    payload = _run(runner.run())

    assert payload.ok is False
    assert payload.status == "failed"
    assert payload.diagnostic is not None
    assert payload.diagnostic["stop_reason"] == {
        "type": "consecutive_tool_errors",
        "count": 2,
        "max_consecutive_tool_errors": 2,
    }
    assert runner._consecutive_tool_errors == 2
    assert len(payload.tool_results) == 2
    assert all(snapshot.status == "failed" for snapshot in payload.tool_results)


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
    monkeypatch.setattr(
        agent._mcp,
        "call_tool_async",
        lambda name, arguments: {
            "ok": True,
            "result": {"ok": True, "tool_name": name},
        },
    )

    runner = _create_runner(agent)

    payload = _run(runner.run())

    assert payload.result_text == "final reply"
    assert payload.reasoning == [
        {"type": "analysis", "text": "gathering data"}
    ]
    assert runner._conversation
    first_assistant = runner._conversation[0]
    assert first_assistant["role"] == "assistant"
    assert first_assistant["reasoning"] == [
        {"type": "analysis", "text": "gathering data"}
    ]
    assert len(payload.tool_results) == 1
    assert payload.tool_results[0].status == "succeeded"


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
    exc.llm_reasoning = (
        {"type": "analysis", "text": "thinking"},
    )
    exc.tool_argument_diagnostics = {
        "call_id": "call-2",
        "tool_name": "broken",
        "preview": "not json",
        "error": {"type": "JSONDecodeError", "message": "bad"},
    }

    recorded_snapshots: list[Mapping[str, Any]] = []

    def recorder(snapshot: Mapping[str, Any]) -> None:
        recorded_snapshots.append(dict(snapshot))

    recorder_instance = _AgentRunRecorder(tool_schemas=None)
    runner = AgentLoopRunner(
        agent=agent,
        recorder=recorder_instance,
        conversation=[],
        cancellation=None,
        on_tool_result=recorder,
        on_llm_step=None,
    )

    iteration = _run(runner._handle_validation_error(exc))

    assert isinstance(iteration.tool_error, Mapping)
    assert iteration.tool_error.get("code") == "VALIDATION_ERROR"
    assert iteration.tool_error.get("message") == "invalid"
    details = iteration.tool_error.get("details", {})
    assert isinstance(details, Mapping)
    assert details.get("type") == "ToolValidationError"
    assert details.get("llm_request_messages") == list(exc.llm_request_messages)
    assert details.get("llm_reasoning") == list(exc.llm_reasoning)
    assert details.get("tool_argument_diagnostics") == exc.tool_argument_diagnostics

    assert len(recorded_snapshots) == 4  # begin + failure for each call
    failed_snapshots = [
        ToolResultSnapshot.from_dict(payload) for payload in recorded_snapshots[1::2]
    ]
    assert all(snapshot.status == "failed" for snapshot in failed_snapshots)
    assert failed_snapshots[0].arguments == {"foo": 1}
    assert failed_snapshots[1].arguments == "not json"

    assert len(runner._conversation) == 3
    assistant_message = runner._conversation[0]
    assert assistant_message["role"] == "assistant"
    tool_calls = assistant_message["tool_calls"]
    assert tool_calls[0]["function"]["arguments"] == json.dumps(
        {"foo": 1}, ensure_ascii=False
    )
    assert tool_calls[1]["function"]["arguments"] == "not json"

    first_tool_message = json.loads(runner._conversation[1]["content"])
    second_tool_message = json.loads(runner._conversation[2]["content"])
    assert first_tool_message["error"]["code"] == "VALIDATION_ERROR"
    assert second_tool_message["error"]["code"] == "VALIDATION_ERROR"
