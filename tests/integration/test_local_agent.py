"""Tests for local agent."""

import asyncio
import json
import threading
from pathlib import Path
from typing import Any
from collections.abc import Mapping

import httpx
import openai
import pytest

import app.agent.local_agent as la
from app.agent.local_agent import LocalAgent
from app.llm.client import LLMClient
from app.llm.types import LLMResponse, LLMToolCall
from app.llm.validation import ToolValidationError
from app.mcp.client import MCPNotReadyError
from app.mcp.utils import ErrorCode
from app.settings import AppSettings
from app.util.cancellation import CancellationEvent, OperationCancelledError

from tests.llm_utils import make_openai_mock, settings_with_llm

pytestmark = pytest.mark.integration


class LLMAsyncBridge:
    async def check_llm_async(self):
        return self.check_llm()

    async def respond_async(
        self,
        conversation,
        *,
        cancellation=None,
    ):
        return self.respond(conversation)


class MCPAsyncBridge:
    async def check_tools_async(self):
        return self.check_tools()

    async def call_tool_async(self, name, arguments):
        return self.call_tool(name, arguments)

    async def ensure_ready_async(self):
        ensure_ready = getattr(self, "ensure_ready", None)
        if callable(ensure_ready):
            ensure_ready()


class SilentLLM(LLMAsyncBridge):
    def check_llm(self):
        return {"ok": True}

    def respond(self, conversation):
        return LLMResponse("", ())


class FailingLLM(LLMAsyncBridge):
    def check_llm(self):
        raise RuntimeError("llm failure")

    def respond(self, conversation):  # pragma: no cover - sanity guard
        raise AssertionError("respond should not be called in this test")


class FailingMCP(MCPAsyncBridge):
    def check_tools(self):
        raise RuntimeError("mcp failure")

    def call_tool(self, name, arguments):
        raise RuntimeError("call fail")


class DummyMCP(MCPAsyncBridge):
    def check_tools(self):
        return {"ok": True, "error": None}

    def call_tool(self, name, arguments):
        raise AssertionError("should not be called")


def _make_validation_error(message: str) -> ToolValidationError:
    error = ToolValidationError(message)
    error.llm_message = ""
    error.llm_tool_calls = [
        {
            "id": "call-0",
            "function": {"name": "list_requirements", "arguments": "{}"},
        }
    ]
    return error


def test_prepare_context_messages_batches_selected_requirement_summaries():
    class RecordingMCP(MCPAsyncBridge):
        def __init__(self):
            self.calls: list[tuple[str, Mapping[str, Any]]] = []

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            self.calls.append((name, arguments))
            assert name == "get_requirement"
            assert arguments["rid"] == ["SYS1", "SYS2"]
            assert arguments["fields"] == ["title", "statement"]
            return {
                "ok": True,
                "result": {
                    "items": [
                        {"rid": "SYS1", "statement": "System overview."},
                        {"rid": "SYS2", "title": "Provide audit log"},
                    ]
                },
            }

    mcp = RecordingMCP()
    agent = LocalAgent(llm=SilentLLM(), mcp=mcp)

    messages = [
        {
            "role": "system",
            "content": (
                "[Workspace context]\n"
                "Selected requirement RIDs: SYS1, SYS2, SYS1"
            ),
        }
    ]

    enriched = asyncio.run(agent._prepare_context_messages_async(messages))

    assert len(mcp.calls) == 1
    expected = (
        "[Workspace context]\n"
        "Selected requirement RIDs: SYS1, SYS2, SYS1\n"
        "SYS1 — System overview.\n"
        "SYS2 — Provide audit log"
    )
    assert enriched[0]["content"] == expected


class JSONFailingLLM(LLMAsyncBridge):
    def check_llm(self):
        return {"ok": True}

    def respond(self, conversation):
        raise json.JSONDecodeError("Expecting value", "", 0)


class OpenAINetworkLLM(LLMAsyncBridge):
    def check_llm(self):
        return {"ok": True}

    def respond(self, conversation):
        request = httpx.Request("GET", "https://example.com")
        raise openai.APIConnectionError(
            message="temporary outage",
            request=request,
        )


def test_check_llm_and_check_tools_propagate_errors():
    agent = LocalAgent(llm=FailingLLM(), mcp=FailingMCP())
    with pytest.raises(RuntimeError, match="llm failure"):
        agent.check_llm()
    with pytest.raises(RuntimeError, match="mcp failure"):
        agent.check_tools()


def test_local_agent_rejects_clients_without_async_interface():
    class LegacyLLM:
        def check_llm(self):  # pragma: no cover - simple stub
            return {"ok": True}

        def respond(self, conversation):  # pragma: no cover - simple stub
            return LLMResponse("", ())

    with pytest.raises(TypeError, match="LLM client must implement async methods"):
        LocalAgent(llm=LegacyLLM(), mcp=DummyMCP())

    class OkLLM(LLMAsyncBridge):
        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            return LLMResponse("", ())

    class LegacyMCP:
        async def check_tools_async(self):  # pragma: no cover - simple stub
            return {"ok": True, "error": None}

    with pytest.raises(TypeError, match="MCP client must implement async methods"):
        LocalAgent(llm=OkLLM(), mcp=LegacyMCP())


def test_run_command_reports_validation_error_for_json_failure():
    agent = LocalAgent(llm=JSONFailingLLM(), mcp=DummyMCP())
    result = agent.run_command("not json")
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert "Expecting value" in result["error"]["message"]
    assert result["error"]["details"]["type"] == "JSONDecodeError"


def test_run_command_reports_llm_tool_validation_details(
    tmp_path: Path, monkeypatch
) -> None:
    settings = settings_with_llm(tmp_path)
    monkeypatch.setattr(
        "openai.OpenAI",
        make_openai_mock(
            {
                "Write the text of the first requirement": [
                    (
                        "create_requirement",
                        {"prefix": "SYS", "data": {"title": "Req-1"}},
                    )
                ]
            }
        ),
    )

    llm_client = LLMClient(settings.llm)

    class ValidatingMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.ensure_calls = 0
            self.call_calls = 0

        def check_tools(self):
            return {"ok": True, "error": None}

        def ensure_ready(self) -> None:
            self.ensure_calls += 1

        def call_tool(self, name, arguments):
            self.call_calls += 1
            error = ToolValidationError(
                "Invalid arguments for create_requirement: data.title is required"
            )
            error.llm_tool_calls = [
                {
                    "id": "tool_call_0",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            ]
            raise error

    mcp = ValidatingMCP()
    agent = LocalAgent(
        llm=llm_client,
        mcp=mcp,
        max_consecutive_tool_errors=1,
    )

    result = agent.run_command("Write the text of the first requirement")

    assert result["ok"] is False
    error = result["error"]
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    details = error.get("details") or {}
    assert details.get("type") == "ToolValidationError"
    tool_calls = details.get("llm_tool_calls")
    assert tool_calls
    first_call = tool_calls[0]
    assert first_call["function"]["name"] == "create_requirement"
    arguments = json.loads(first_call["function"]["arguments"])
    assert arguments["data"]["title"] == "Req-1"
    diagnostic = result.get("diagnostic")
    assert diagnostic
    requests = diagnostic["llm_requests"]
    assert isinstance(requests, list) and requests
    first_request = requests[0]
    assert first_request["step"] == 1
    assert first_request["messages"][-1]["content"].startswith(
        "Write the text of the first requirement"
    )
    steps = diagnostic.get("llm_steps")
    assert isinstance(steps, list) and steps
    assert steps[0]["step"] == 1
    assert mcp.call_calls == 1
    assert mcp.ensure_calls == 1


def test_run_command_reports_internal_error_for_openai_failure():
    agent = LocalAgent(llm=OpenAINetworkLLM(), mcp=DummyMCP())
    result = agent.run_command("anything")
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INTERNAL
    assert result["error"]["message"] == "temporary outage"
    assert result["error"]["details"]["type"] == "APIConnectionError"


def test_run_command_does_not_inject_validation_fallback_message():
    class EmptyValidationLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.calls = 0

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            self.calls += 1
            raise _make_validation_error(
                "Invalid arguments for list_requirements: per_page is required"
            )

    llm = EmptyValidationLLM()
    agent = LocalAgent(
        llm=llm,
        mcp=DummyMCP(),
        max_consecutive_tool_errors=1,
    )

    result = agent.run_command("list requirements")

    assert llm.calls == 1
    assert result["ok"] is False
    error = result["error"]
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert (
        error["message"]
        == "Invalid arguments for list_requirements: per_page is required"
    )
    details = error.get("details") or {}
    assert details.get("type") == "ToolValidationError"
    fallback_message = details.get("llm_message")
    assert fallback_message == ""
    stop_reason = result.get("agent_stop_reason") or {}
    assert stop_reason.get("type") == "consecutive_tool_errors"
    assert stop_reason.get("count") == 1


def test_agent_relays_missing_required_tool_arguments_to_mcp():
    class MissingRidLLM(LLMAsyncBridge):
        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            return LLMResponse(
                content="",
                tool_calls=(
                    LLMToolCall(
                        id="call-0",
                        name="update_requirement_field",
                        arguments={"field": "title", "value": "Новый заголовок"},
                    ),
                ),
            )

    class RecordingMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.ensure_calls = 0
            self.call_args: list[tuple[str, Mapping[str, Any]]] = []

        def check_tools(self):
            return {"ok": True, "error": None}

        def ensure_ready(self):
            self.ensure_calls += 1

        def call_tool(self, name, arguments):
            self.call_args.append((name, dict(arguments)))
            exc = ToolValidationError("Invalid arguments from MCP: rid is required")
            exc.error_payload = {
                "code": ErrorCode.VALIDATION_ERROR,
                "message": "Invalid arguments from MCP: rid is required",
                "details": {"type": "ToolValidationError"},
            }
            raise exc

    mcp = RecordingMCP()
    agent = LocalAgent(
        llm=MissingRidLLM(),
        mcp=mcp,
        max_consecutive_tool_errors=1,
    )

    result = agent.run_command("translate demo requirements")

    assert mcp.ensure_calls == 1
    assert len(mcp.call_args) == 1
    name, arguments = mcp.call_args[0]
    assert name == "update_requirement_field"
    assert "rid" not in arguments
    assert result["ok"] is False
    error = result["error"]
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert error["message"] == "Invalid arguments from MCP: rid is required"
    details = error.get("details") or {}
    assert details.get("type") == "ToolValidationError"


def test_run_command_propagates_mcp_exception():
    class ToolCallingLLM(LLMAsyncBridge):
        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            return LLMResponse(
                content="",
                tool_calls=(
                    LLMToolCall(id="call-0", name="list_requirements", arguments={}),
                ),
            )

    agent = LocalAgent(llm=ToolCallingLLM(), mcp=FailingMCP())
    result = agent.run_command("text")
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert result["error"]["message"] == "call fail"


def test_run_command_aborts_when_mcp_unavailable():
    class ToolCallingLLM(LLMAsyncBridge):
        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            return LLMResponse(
                "",
                (
                    LLMToolCall(
                        id="call-0",
                        name="list_requirements",
                        arguments={},
                    ),
                ),
            )

        async def respond_async(self, conversation, *, cancellation=None):
            return self.respond(conversation)

    class UnavailableMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.ensure_calls = 0

        def check_tools(self):
            return {"ok": False, "error": None}

        def ensure_ready(self) -> None:
            self.ensure_calls += 1
            raise MCPNotReadyError({"code": "INTERNAL", "message": "server offline"})

        def call_tool(self, name, arguments):  # pragma: no cover - should not be reached
            raise AssertionError("tool call must be skipped when MCP is offline")

    llm = ToolCallingLLM()
    mcp = UnavailableMCP()
    agent = LocalAgent(
        llm=llm,
        mcp=mcp,
        max_consecutive_tool_errors=1,
    )

    result = agent.run_command("list")
    expected_error = {"code": "INTERNAL", "message": "server offline"}
    assert result["ok"] is False
    assert result["error"] == expected_error
    assert result["tool_name"] == "list_requirements"
    assert result["tool_call_id"] == "call-0"
    assert result["call_id"] == "call-0"
    assert result.get("tool_arguments") == {}
    assert "tool_results" not in result
    assert result["agent_stop_reason"] == {
        "type": "consecutive_tool_errors",
        "count": 1,
        "max_consecutive_tool_errors": 1,
    }
    assert mcp.ensure_calls == 1
    assert agent.max_consecutive_tool_errors == 1

    async def exercise() -> None:
        async_result = await agent.run_command_async("list async")
        assert async_result["ok"] is False
        assert async_result["error"] == expected_error
        assert async_result["tool_name"] == "list_requirements"
        assert async_result["tool_call_id"] == "call-0"
        assert async_result["call_id"] == "call-0"
        assert async_result.get("tool_arguments") == {}
        assert "tool_results" not in async_result
        assert async_result["agent_stop_reason"] == {
            "type": "consecutive_tool_errors",
            "count": 1,
            "max_consecutive_tool_errors": 1,
        }

    asyncio.run(exercise())
    assert mcp.ensure_calls == 2


def test_run_command_executes_tool_and_returns_final_message():
    class SequencedLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.calls = 0
            self.last_conversation: list[dict[str, Any]] | None = None

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    "One moment, checking",
                    (
                        LLMToolCall(
                            id="call-0",
                            name="list_requirements",
                            arguments={"per_page": 1},
                        ),
                    ),
                )
            self.last_conversation = list(conversation)
            return LLMResponse("Found 0 records", ())

    class RecordingMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.calls: list[tuple[str, Mapping[str, Any]]] = []

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            self.calls.append((name, dict(arguments)))
            return {"ok": True, "error": None, "result": {"items": []}}

    llm = SequencedLLM()
    mcp = RecordingMCP()
    agent = LocalAgent(llm=llm, mcp=mcp)

    result = agent.run_command("list latest")
    assert result["ok"] is True
    assert result["result"] == "Found 0 records"
    assert result.get("tool_results")
    first_tool = result["tool_results"][0]
    assert first_tool["result"]["items"] == []
    assert first_tool["ok"] is True
    assert first_tool["tool_name"] == "list_requirements"
    assert first_tool["tool_arguments"] == {"per_page": 1}
    assert first_tool["tool_call_id"] == "call-0"
    assert first_tool["call_id"] == "call-0"
    for tool_payload in result["tool_results"]:
        assert "tool_name" in tool_payload
        assert "tool_arguments" in tool_payload
        assert "tool_call_id" in tool_payload
        assert "call_id" in tool_payload
    assert mcp.calls == [("list_requirements", {"per_page": 1})]
    assert llm.last_conversation is not None
    assert llm.last_conversation[-1]["role"] == "tool"
    tool_message = json.loads(llm.last_conversation[-1]["content"])
    assert tool_message["tool_name"] == "list_requirements"
    assert tool_message["tool_call_id"] == "call-0"
    assert tool_message["call_id"] == "call-0"
    assert tool_message["tool_arguments"] == {"per_page": 1}
    assert tool_message["ok"] is True
    assert tool_message["error"] is None
    assert tool_message["result"] == {"items": []}


def test_run_command_returns_tool_error_result():
    class ToolLLM(LLMAsyncBridge):
        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            return LLMResponse(
                "",
                (
                    LLMToolCall(
                        id="call-0",
                        name="list_requirements",
                        arguments={},
                    ),
                ),
            )

    class ErrorMCP(MCPAsyncBridge):
        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.INTERNAL,
                    "message": "boom",
                },
            }

    agent = LocalAgent(
        llm=ToolLLM(),
        mcp=ErrorMCP(),
        max_consecutive_tool_errors=1,
    )
    result = agent.run_command("list")
    expected_error = {"code": ErrorCode.INTERNAL, "message": "boom"}
    assert result["ok"] is False
    assert result["error"] == expected_error
    assert result["tool_name"] == "list_requirements"
    assert result["tool_call_id"] == "call-0"
    assert result["call_id"] == "call-0"
    assert result.get("tool_arguments") == {}
    assert "tool_results" not in result
    assert result["agent_stop_reason"] == {
        "type": "consecutive_tool_errors",
        "count": 1,
        "max_consecutive_tool_errors": 1,
    }
    assert agent.max_consecutive_tool_errors == 1


def test_run_command_recovers_after_tool_error():
    class RecoveringLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.calls = 0
            self.conversations: list[list[dict[str, Any]]] = []

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            cloned = [dict(message) for message in conversation]
            self.conversations.append(cloned)
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    "",
                    (
                        LLMToolCall(
                            id="call-0",
                            name="adjust_requirement",
                            arguments={"value": "bad"},
                        ),
                    ),
                )
            if self.calls == 2:
                tool_reply = json.loads(conversation[-1]["content"])
                assert tool_reply["ok"] is False
                assert tool_reply["error"]["message"] == "invalid value"
                return LLMResponse(
                    "",
                    (
                        LLMToolCall(
                            id="call-1",
                            name="adjust_requirement",
                            arguments={"value": "good"},
                        ),
                    ),
                )
            return LLMResponse("Done", ())

    class FlakyMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.calls: list[tuple[str, Mapping[str, Any]]] = []

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            self.calls.append((name, dict(arguments)))
            if len(self.calls) == 1:
                return {
                    "ok": False,
                    "error": {
                        "code": ErrorCode.VALIDATION_ERROR,
                        "message": "invalid value",
                    },
                }
            return {
                "ok": True,
                "error": None,
                "result": {"value": arguments["value"]},
            }

    llm = RecoveringLLM()
    mcp = FlakyMCP()
    agent = LocalAgent(llm=llm, mcp=mcp)

    result = agent.run_command("adjust please")

    assert result["ok"] is True
    assert result["result"] == "Done"
    assert "agent_stop_reason" not in result
    assert result.get("tool_results")
    assert result["tool_results"][0]["tool_name"] == "adjust_requirement"
    assert result["tool_results"][0]["result"] == {"value": "good"}
    assert result["tool_results"][0]["ok"] is True
    assert agent.max_consecutive_tool_errors == 5

    assert llm.calls == 3
    assert [call[0] for call in mcp.calls] == [
        "adjust_requirement",
        "adjust_requirement",
    ]
    assert len(llm.conversations) >= 3
    error_message = json.loads(llm.conversations[1][-1]["content"])
    assert error_message["ok"] is False
    assert error_message["error"]["message"] == "invalid value"


def test_run_command_stops_after_configured_tool_error_limit():
    class LoopingToolLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.calls = 0
            self.conversations: list[list[dict[str, Any]]] = []

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            self.conversations.append([dict(message) for message in conversation])
            self.calls += 1
            return LLMResponse(
                "",
                (
                    LLMToolCall(
                        id=f"call-{self.calls}",
                        name="always_fails",
                        arguments={"step": self.calls},
                    ),
                ),
            )

    class AlwaysFailingMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.calls: list[tuple[str, Mapping[str, Any]]] = []

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            self.calls.append((name, dict(arguments)))
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.INTERNAL,
                    "message": f"failure {len(self.calls)}",
                },
            }

    llm = LoopingToolLLM()
    mcp = AlwaysFailingMCP()
    agent = LocalAgent(llm=llm, mcp=mcp, max_consecutive_tool_errors=3)

    result = agent.run_command("loop")

    assert result["ok"] is False
    assert result["error"]["message"] == "failure 3"
    assert result["tool_name"] == "always_fails"
    assert result["agent_stop_reason"] == {
        "type": "consecutive_tool_errors",
        "count": 3,
        "max_consecutive_tool_errors": 3,
    }
    assert agent.max_consecutive_tool_errors == 3


def test_run_command_respects_cancellation_after_tool_batch():
    cancellation = CancellationEvent()

    class ToolLLM(LLMAsyncBridge):
        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            return LLMResponse(
                "",
                (
                    LLMToolCall(
                        id="call-0",
                        name="list_requirements",
                        arguments={},
                    ),
                ),
            )

    class CancellingMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.calls: list[tuple[str, Mapping[str, Any]]] = []

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            self.calls.append((name, dict(arguments)))
            cancellation.set()
            return {"ok": True, "error": None, "result": {"status": "ok"}}

    agent = LocalAgent(llm=ToolLLM(), mcp=CancellingMCP())

    with pytest.raises(OperationCancelledError):
        agent.run_command("cancel later", cancellation=cancellation)


def test_run_command_recovers_after_tool_validation_error():
    class ValidationAwareLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.calls = 0
            self.conversations: list[list[dict[str, Any]]] = []

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            cloned = [dict(message) for message in conversation]
            self.conversations.append(cloned)
            self.calls += 1
            if self.calls == 1:
                exc = ToolValidationError(
                    "Invalid arguments for update_requirement_field: value: "
                    "'in_last_review' is not one of ['draft', 'in_review', 'approved', "
                    "'baselined', 'retired']"
                )
                exc.llm_message = ""
                exc.llm_request_messages = tuple(
                    dict(message) for message in conversation
                )
                exc.llm_tool_calls = (
                    {
                        "id": "call-0",
                        "type": "function",
                        "function": {
                            "name": "update_requirement_field",
                            "arguments": json.dumps(
                                {
                                    "rid": "SYS1",
                                    "field": "status",
                                    "value": "in_last_review",
                                },
                                ensure_ascii=False,
                            ),
                        },
                    },
                )
                raise exc
            if self.calls == 2:
                tool_reply = json.loads(conversation[-1]["content"])
                assert tool_reply["ok"] is False
                assert tool_reply["error"]["message"].startswith(
                    "Invalid arguments for update_requirement_field"
                )
                assert tool_reply.get("tool_arguments", {}).get("value") == "in_last_review"
                return LLMResponse(
                    "",
                    (
                        LLMToolCall(
                            id="call-1",
                            name="update_requirement_field",
                            arguments={
                                "rid": "SYS1",
                                "field": "status",
                                "value": "in_review",
                            },
                        ),
                    ),
                )
            return LLMResponse("Done", ())

    class TrackingMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.calls: list[tuple[str, Mapping[str, Any]]] = []

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            self.calls.append((name, dict(arguments)))
            return {
                "ok": True,
                "error": None,
                "result": {"value": arguments["value"]},
            }

    llm = ValidationAwareLLM()
    mcp = TrackingMCP()
    agent = LocalAgent(llm=llm, mcp=mcp)

    result = agent.run_command("adjust please")

    assert result["ok"] is True
    assert result["result"] == "Done"
    assert result.get("tool_results")
    assert result["tool_results"][0]["result"] == {"value": "in_review"}
    assert llm.calls == 3
    assert len(mcp.calls) == 1
    assert mcp.calls[0][0] == "update_requirement_field"
    forwarded_arguments = mcp.calls[0][1]
    assert forwarded_arguments["rid"] == "SYS1"
    assert forwarded_arguments["value"] == "in_review"
    assert len(llm.conversations) >= 2
    second_attempt = llm.conversations[1]
    assert second_attempt[-1]["role"] == "tool"
    payload = json.loads(second_attempt[-1]["content"])
    assert payload["error"]["message"].startswith(
        "Invalid arguments for update_requirement_field"
    )
    tool_arguments = payload.get("tool_arguments", {})
    assert tool_arguments.get("rid") == "SYS1"
    assert tool_arguments.get("value") == "in_last_review"
    diagnostic = result.get("diagnostic")
    assert diagnostic
    requests = diagnostic["llm_requests"]
    assert isinstance(requests, list)
    assert len(requests) >= 1
    first_request = requests[0]
    assert first_request["step"] == 1
    first_messages = first_request["messages"]
    assert first_messages[-1]["role"] == "user"
    assert first_messages[-1]["content"] == "adjust please"


def test_run_command_forwards_complete_tool_arguments_to_mcp():
    class ForwardingLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.step = 0
            self.conversations: list[list[dict[str, Any]]] = []

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            self.conversations.append([dict(message) for message in conversation])
            if self.step == 0:
                self.step += 1
                return LLMResponse(
                    "",
                    (
                        LLMToolCall(
                            id="call-0",
                            name="update_requirement_field",
                            arguments={
                                "rid": "SYS9",
                                "field": "status",
                                "value": "approved",
                                "comment": "review completed",
                            },
                        ),
                    ),
                )
            self.step += 1
            return LLMResponse("All done", ())

    class RecordingMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.calls: list[tuple[str, Mapping[str, Any]]] = []

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            captured = dict(arguments)
            self.calls.append((name, captured))
            return {
                "ok": True,
                "error": None,
                "result": {"status": "updated", "rid": captured.get("rid")},
            }

    llm = ForwardingLLM()
    mcp = RecordingMCP()
    agent = LocalAgent(llm=llm, mcp=mcp)

    result = agent.run_command("approve SYS9")

    assert result["ok"] is True
    assert result["result"] == "All done"
    tool_results = result.get("tool_results") or []
    assert len(tool_results) == 1
    tool_payload = tool_results[0]
    assert tool_payload["tool_name"] == "update_requirement_field"
    forwarded_arguments = tool_payload.get("tool_arguments") or {}
    assert forwarded_arguments.get("rid") == "SYS9"
    assert forwarded_arguments.get("field") == "status"
    assert forwarded_arguments.get("value") == "approved"
    assert forwarded_arguments.get("comment") == "review completed"
    assert tool_payload.get("result", {}).get("rid") == "SYS9"

    assert len(mcp.calls) == 1
    mcp_call_name, mcp_arguments = mcp.calls[0]
    assert mcp_call_name == "update_requirement_field"
    assert mcp_arguments == {
        "rid": "SYS9",
        "field": "status",
        "value": "approved",
        "comment": "review completed",
    }

    assert len(llm.conversations) >= 2
    second_turn = llm.conversations[1]
    assert second_turn[-1]["role"] == "tool"
    tool_payload = json.loads(second_turn[-1]["content"])
    assert tool_payload["tool_arguments"]["rid"] == "SYS9"
    assert tool_payload["tool_arguments"]["comment"] == "review completed"


def test_run_command_streams_tool_results_to_callback():
    class SequencedLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.step = 0

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            if self.step == 0:
                self.step += 1
                return LLMResponse(
                    "",
                    (
                        LLMToolCall(
                            id="call-0",
                            name="list_requirements",
                            arguments={"per_page": 5},
                        ),
                        LLMToolCall(
                            id="call-1",
                            name="get_requirement",
                            arguments={"rid": "SYS-0001"},
                        ),
                    ),
                )
            return LLMResponse("All done", ())

    class StreamingMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.calls: list[tuple[str, Mapping[str, Any]]] = []

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            self.calls.append((name, dict(arguments)))
            return {"ok": True, "error": None, "result": {"status": name}}

    llm = SequencedLLM()
    mcp = StreamingMCP()
    agent = LocalAgent(llm=llm, mcp=mcp)

    collected: list[Mapping[str, Any]] = []

    def capture(payload: Mapping[str, Any]) -> None:
        collected.append(dict(payload))

    result = agent.run_command("stream tools", on_tool_result=capture)

    assert result["ok"] is True
    assert result["result"] == "All done"
    assert len(collected) == 4
    running_updates = [
        payload for payload in collected if payload.get("agent_status") == "running"
    ]
    assert [payload["tool_name"] for payload in running_updates] == [
        "list_requirements",
        "get_requirement",
    ]
    completed_updates = [
        payload
        for payload in collected
        if payload.get("agent_status") and payload.get("agent_status") != "running"
    ]
    assert [payload.get("agent_status") for payload in completed_updates] == [
        "completed",
        "completed",
    ]
    assert [payload["tool_name"] for payload in completed_updates] == [
        "list_requirements",
        "get_requirement",
    ]
    assert [call[0] for call in mcp.calls] == ["list_requirements", "get_requirement"]
    assert result.get("tool_results")
    assert [
        payload["tool_name"] for payload in result["tool_results"]
    ] == ["list_requirements", "get_requirement"]
    assert [
        payload.get("agent_status") for payload in result["tool_results"]
    ] == ["completed", "completed"]
    for streamed, final in zip(
        completed_updates, result["tool_results"], strict=True
    ):
        assert streamed == final
        assert streamed is not final


def test_run_command_reports_loop_details_when_max_steps_exceeded():
    class LoopingLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.calls = 0

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            self.calls += 1
            return LLMResponse(
                "",
                (
                    LLMToolCall(
                        id=f"call-{self.calls}",
                        name="get_requirement",
                        arguments={"rid": "SYS-8"},
                    ),
                ),
            )

    class RecordingMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.calls: list[tuple[str, Mapping[str, Any]]] = []

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            self.calls.append((name, dict(arguments)))
            return {
                "ok": True,
                "error": None,
                "result": {"rid": "SYS-8", "title": "Loop"},
            }

    llm = LoopingLLM()
    mcp = RecordingMCP()
    agent = LocalAgent(llm=llm, mcp=mcp, max_thought_steps=5)

    result = agent.run_command("show SYS-8")

    assert result["ok"] is False
    error = result["error"]
    assert error["code"] == ErrorCode.VALIDATION_ERROR
    assert "get_requirement" in error["message"]
    assert "SYS-8" in error["message"]
    details = error.get("details") or {}
    assert details.get("type") == "ToolValidationError"
    tool_calls = details.get("llm_tool_calls")
    assert isinstance(tool_calls, list) and tool_calls
    last_call = tool_calls[-1]
    assert last_call["name"] == "get_requirement"
    assert last_call["arguments"]["rid"] == "SYS-8"
    tool_results = details.get("tool_results")
    assert isinstance(tool_results, list) and tool_results
    last_result = tool_results[-1]
    assert last_result["tool_name"] == "get_requirement"
    assert last_result["tool_arguments"]["rid"] == "SYS-8"
    assert agent.max_thought_steps == 5
    assert len(mcp.calls) == agent.max_thought_steps


def test_run_command_handles_long_sequences_without_step_limit():
    class LongSequenceLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.calls = 0

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            self.calls += 1
            if self.calls <= 10:
                return LLMResponse(
                    "",
                    (
                        LLMToolCall(
                            id=f"call-{self.calls}",
                            name="get_requirement",
                            arguments={"rid": f"SYS-{self.calls:04d}"},
                        ),
                    ),
                )
            return LLMResponse("done", ())

    class CountingMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.calls: list[tuple[str, Mapping[str, Any]]] = []

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            self.calls.append((name, dict(arguments)))
            return {"ok": True, "error": None, "result": {"rid": arguments["rid"]}}

    llm = LongSequenceLLM()
    mcp = CountingMCP()
    agent = LocalAgent(llm=llm, mcp=mcp)

    result = agent.run_command("request a series of requirements")

    assert agent.max_thought_steps is None
    assert result["ok"] is True
    assert result["result"] == "done"
    assert len(mcp.calls) == 10
    assert [call[1]["rid"] for call in mcp.calls] == [
        f"SYS-{index:04d}" for index in range(1, 11)
    ]


def test_run_command_returns_message_without_mcp_call():
    class MessageLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.conversations: list[list[dict[str, Any]]] = []

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            self.conversations.append(list(conversation))
            return LLMResponse("Hello!", ())

        async def respond_async(self, conversation, *, cancellation=None):
            return self.respond(conversation)

    class RecordingMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.called = False

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            self.called = True
            return {"ok": True, "error": None, "result": {}}

    llm = MessageLLM()
    mcp = RecordingMCP()
    agent = LocalAgent(llm=llm, mcp=mcp)

    result = agent.run_command("hi")
    assert result["ok"] is True
    assert result["error"] is None
    assert result["result"] == "Hello!"
    diagnostic = result.get("diagnostic")
    assert isinstance(diagnostic, dict)
    steps = diagnostic.get("llm_steps")
    assert isinstance(steps, list) and steps
    assert mcp.called is False
    assert llm.conversations[0][-1] == {"role": "user", "content": "hi"}
    assert "tool_results" not in result

    async def exercise() -> None:
        async_result = await agent.run_command_async("more")
        assert async_result["ok"] is True
        assert async_result["error"] is None
        assert async_result["result"] == "Hello!"
        diag_async = async_result.get("diagnostic")
        assert isinstance(diag_async, dict)
        async_steps = diag_async.get("llm_steps")
        assert isinstance(async_steps, list) and async_steps
        assert "tool_results" not in async_result

    asyncio.run(exercise())
    assert mcp.called is False
    assert llm.conversations[1][-1] == {"role": "user", "content": "more"}


def test_run_command_attaches_llm_request_messages():
    class RecordingLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.conversations: list[list[dict[str, Any]]] = []

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            cloned = [dict(message) for message in conversation]
            self.conversations.append(cloned)
            return LLMResponse(
                "Answer",
                (),
                request_messages=tuple(dict(message) for message in conversation),
            )

    llm = RecordingLLM()
    agent = LocalAgent(llm=llm, mcp=DummyMCP())

    result = agent.run_command("hello")

    diagnostic = result.get("diagnostic")
    assert diagnostic
    requests = diagnostic["llm_requests"]
    assert isinstance(requests, list) and len(requests) == 1
    first_entry = requests[0]
    assert first_entry["step"] == 1
    messages = first_entry["messages"]
    assert messages[-1]["content"] == "hello"
    assert messages[0]["role"] == "user"


def test_run_command_records_full_llm_request_sequence():
    class MultiStepLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.conversations: list[list[dict[str, Any]]] = []
            self.calls = 0

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            cloned = [dict(message) for message in conversation]
            self.conversations.append(cloned)
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    "",
                    (
                        LLMToolCall(
                            id="call-1",
                            name="demo_tool",
                            arguments={"echo": "value"},
                        ),
                    ),
                    request_messages=tuple(dict(message) for message in conversation),
                )
            return LLMResponse(
                "Done",
                (),
                request_messages=tuple(dict(message) for message in conversation),
            )

    class EchoMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.tool_calls: list[tuple[str, Mapping[str, Any]]] = []

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            self.tool_calls.append((name, dict(arguments)))
            return {
                "ok": True,
                "error": None,
                "result": {"echo": arguments},
            }

    llm = MultiStepLLM()
    mcp = EchoMCP()
    agent = LocalAgent(llm=llm, mcp=mcp)

    result = agent.run_command("start")

    assert result["ok"] is True
    diagnostic = result.get("diagnostic")
    assert diagnostic
    requests = diagnostic["llm_requests"]
    assert isinstance(requests, list)
    assert len(requests) == 2

    first_request = requests[0]
    assert first_request["step"] == 1
    assert [msg["role"] for msg in first_request["messages"]] == ["user"]

    second_request = requests[1]
    assert second_request["step"] == 2
    second_roles = [msg["role"] for msg in second_request["messages"]]
    assert second_roles[-2:] == ["assistant", "tool"]
    assert second_request["messages"][0]["content"] == "start"

    assert len(mcp.tool_calls) == 1
    assert mcp.tool_calls[0][0] == "demo_tool"


def test_run_command_passes_history_to_llm():
    class RecordingLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.conversations: list[list[dict[str, Any]]] = []

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            self.conversations.append(list(conversation))
            return LLMResponse("Done", ())

    class SilentMCP(MCPAsyncBridge):
        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            raise AssertionError("tool should not be invoked")

    llm = RecordingLLM()
    agent = LocalAgent(llm=llm, mcp=SilentMCP())
    history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]

    agent.run_command("next", history=history)
    assert llm.conversations[0] == [
        *history,
        {"role": "user", "content": "next"},
    ]

    asyncio.run(agent.run_command_async("again", history=history))
    assert llm.conversations[1] == [
        *history,
        {"role": "user", "content": "again"},
    ]


def test_run_command_includes_context_messages():
    class RecordingLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.conversations: list[list[dict[str, Any]]] = []

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            self.conversations.append(list(conversation))
            return LLMResponse("done", ())

    class PassiveMCP(MCPAsyncBridge):
        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            raise AssertionError("tool should not be invoked")

    llm = RecordingLLM()
    agent = LocalAgent(llm=llm, mcp=PassiveMCP())
    context_message = {
        "role": "system",
        "content": (
            "Selected requirement RIDs: SYS-1"
        ),
    }

    agent.run_command("execute", context=context_message)
    assert llm.conversations[0][-2] == context_message
    assert llm.conversations[0][-1] == {"role": "user", "content": "execute"}

    async def exercise() -> None:
        await agent.run_command_async(
            "repeat",
            context=[
                {
                    "role": "system",
                    "content": (
                        "Selected requirement RIDs: SYS-2"
                    ),
                }
            ],
        )

    asyncio.run(exercise())
    assert llm.conversations[1][-2] == {
        "role": "system",
        "content": (
            "Selected requirement RIDs: SYS-2"
        ),
    }
    assert llm.conversations[1][-1] == {"role": "user", "content": "repeat"}


def test_custom_confirm_message(monkeypatch):
    messages = []

    def custom_confirm(msg: str) -> bool:
        messages.append(msg)
        return True

    class StubLLM(LLMAsyncBridge):
        def __init__(self, settings):
            self._calls = 0

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            self._calls += 1
            if self._calls == 1:
                return LLMResponse(
                    "",
                    (
                        LLMToolCall(
                            id="call-0",
                            name="delete_requirement",
                            arguments={"rid": "SYS-1"},
                        ),
                    ),
                )
            return LLMResponse("Deleted", ())

        async def respond_async(self, conversation, *, cancellation=None):
            return self.respond(conversation)

    class StubMCP(MCPAsyncBridge):
        def __init__(
            self,
            settings,
            *,
            confirm,
            confirm_requirement_update=None,
        ):
            self.confirm = confirm
            self.confirm_requirement_update = confirm_requirement_update

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            if name == "delete_requirement" or name in {
                "update_requirement_field",
                "set_requirement_labels",
                "set_requirement_attachments",
                "set_requirement_links",
            }:
                self.confirm("Delete requirement?")
            return {"ok": True, "error": None, "result": {}}

    monkeypatch.setattr(la, "LLMClient", StubLLM)
    monkeypatch.setattr(la, "MCPClient", StubMCP)
    agent = LocalAgent(settings=AppSettings(), confirm=custom_confirm)
    result = agent.run_command("remove")
    assert result["ok"] is True
    assert result["result"] == "Deleted"
    assert result.get("tool_results")
    assert result["tool_results"][0]["ok"] is True
    for tool_payload in result["tool_results"]:
        assert "tool_name" in tool_payload
        assert "tool_arguments" in tool_payload
        assert "tool_call_id" in tool_payload
        assert "call_id" in tool_payload
    assert messages == ["Delete requirement?"]


def test_async_methods_offload_to_threads():
    main_thread = threading.get_ident()

    class RecordingLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.check_thread: int | None = None
            self.respond_thread: int | None = None
            self.calls = 0

        def check_llm(self):
            self.check_thread = threading.get_ident()
            return {"ok": True}

        def respond(self, conversation):
            self.respond_thread = threading.get_ident()
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    "",
                    (
                        LLMToolCall(
                            id="call-0",
                            name="list_requirements",
                            arguments={},
                        ),
                    ),
                )
            return LLMResponse("done", ())

        async def check_llm_async(self):
            return await asyncio.to_thread(self.check_llm)

        async def respond_async(self, conversation, *, cancellation=None):
            return await asyncio.to_thread(self.respond, conversation)

    class RecordingMCP(MCPAsyncBridge):
        def __init__(self) -> None:
            self.check_thread: int | None = None
            self.call_thread: int | None = None

        def check_tools(self):
            self.check_thread = threading.get_ident()
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            self.call_thread = threading.get_ident()
            return {"ok": True, "error": None, "result": {}}

        async def check_tools_async(self):
            return await asyncio.to_thread(self.check_tools)

        async def call_tool_async(self, name, arguments):
            return await asyncio.to_thread(self.call_tool, name, arguments)

    llm = RecordingLLM()
    mcp = RecordingMCP()
    agent = LocalAgent(llm=llm, mcp=mcp)

    async def exercise() -> None:
        assert await agent.check_llm_async() == {"ok": True}
        assert await agent.check_tools_async() == {"ok": True, "error": None}
        result = await agent.run_command_async("anything")
        assert result["ok"] is True
        assert result["result"] == "done"
        assert result.get("tool_results")
        assert result["tool_results"][0]["ok"] is True
        for tool_payload in result["tool_results"]:
            assert "tool_name" in tool_payload
            assert "tool_arguments" in tool_payload
            assert "tool_call_id" in tool_payload
            assert "call_id" in tool_payload

    asyncio.run(exercise())

    assert llm.check_thread is not None and llm.check_thread != main_thread
    assert llm.respond_thread is not None and llm.respond_thread != main_thread
    assert mcp.check_thread is not None and mcp.check_thread != main_thread
    assert mcp.call_thread is not None and mcp.call_thread != main_thread


def test_async_methods_prefer_native_coroutines():
    class AsyncLLM:
        def __init__(self) -> None:
            self.check_called = False
            self.respond_called = False
            self._calls = 0

        async def check_llm_async(self):
            self.check_called = True
            return {"ok": True}

        async def respond_async(self, conversation, *, cancellation=None):
            self.respond_called = True
            self._calls += 1
            if self._calls == 1:
                return LLMResponse(
                    "",
                    (
                        LLMToolCall(
                            id="call-0",
                            name="list_requirements",
                            arguments={},
                        ),
                    ),
                )
            return LLMResponse("done", ())

    class AsyncMCP:
        def __init__(self) -> None:
            self.check_called = False
            self.call_called = False

        async def check_tools_async(self):
            self.check_called = True
            return {"ok": True, "error": None}

        async def call_tool_async(self, name, arguments):
            self.call_called = True
            return {"ok": True, "error": None, "result": {}}

        async def ensure_ready_async(self):
            return None

    llm = AsyncLLM()
    mcp = AsyncMCP()
    agent = LocalAgent(llm=llm, mcp=mcp)

    async def exercise() -> None:
        assert await agent.check_llm_async() == {"ok": True}
        assert await agent.check_tools_async() == {"ok": True, "error": None}
        result = await agent.run_command_async("text")
        assert result["ok"] is True
        assert result["result"] == "done"
        assert result.get("tool_results")
        assert result["tool_results"][0]["ok"] is True
        for tool_payload in result["tool_results"]:
            assert "tool_name" in tool_payload
            assert "tool_arguments" in tool_payload
            assert "tool_call_id" in tool_payload
            assert "call_id" in tool_payload

    asyncio.run(exercise())

    assert llm.check_called is True
    assert llm.respond_called is True
    assert mcp.check_called is True
    assert mcp.call_called is True
