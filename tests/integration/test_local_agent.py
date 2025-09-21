"""Tests for local agent."""

import asyncio
import json
import threading
from typing import Any, Mapping

import httpx
import openai
import pytest

from app.agent import local_agent as la
from app.agent.local_agent import LocalAgent
from app.llm.client import LLMResponse, LLMToolCall
from app.mcp.client import MCPNotReadyError
from app.mcp.utils import ErrorCode
from app.settings import AppSettings

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


def test_run_command_reports_internal_error_for_openai_failure():
    agent = LocalAgent(llm=OpenAINetworkLLM(), mcp=DummyMCP())
    result = agent.run_command("anything")
    assert result["ok"] is False
    assert result["error"]["code"] == ErrorCode.INTERNAL
    assert result["error"]["message"] == "temporary outage"
    assert result["error"]["details"]["type"] == "APIConnectionError"


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
    agent = LocalAgent(llm=llm, mcp=mcp)

    result = agent.run_command("list")
    assert result == {"ok": False, "error": {"code": "INTERNAL", "message": "server offline"}}
    assert mcp.ensure_calls == 1

    async def exercise() -> None:
        async_result = await agent.run_command_async("list async")
        assert async_result == {"ok": False, "error": {"code": "INTERNAL", "message": "server offline"}}

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
                    "Секунду, посмотрю",
                    (
                        LLMToolCall(
                            id="call-0",
                            name="list_requirements",
                            arguments={"per_page": 1},
                        ),
                    ),
                )
            self.last_conversation = list(conversation)
            return LLMResponse("Нашёл 0 записей", ())

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
    assert result["result"] == "Нашёл 0 записей"
    assert result.get("tool_results")
    first_tool = result["tool_results"][0]
    assert first_tool["result"]["items"] == []
    assert first_tool["ok"] is True
    assert first_tool["tool_name"] == "list_requirements"
    assert first_tool["tool_arguments"] == {"per_page": 1}
    for tool_payload in result["tool_results"]:
        assert "tool_name" in tool_payload
        assert "tool_arguments" in tool_payload
    assert mcp.calls == [("list_requirements", {"per_page": 1})]
    assert llm.last_conversation is not None
    assert llm.last_conversation[-1]["role"] == "tool"
    assert json.loads(llm.last_conversation[-1]["content"]) == {
        "ok": True,
        "error": None,
        "result": {"items": []},
    }


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

    agent = LocalAgent(llm=ToolLLM(), mcp=ErrorMCP())
    result = agent.run_command("list")
    assert result == {
        "ok": False,
        "error": {"code": ErrorCode.INTERNAL, "message": "boom"},
    }
    assert "tool_results" not in result


def test_run_command_returns_message_without_mcp_call():
    class MessageLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.conversations: list[list[dict[str, Any]]] = []

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            self.conversations.append(list(conversation))
            return LLMResponse("Привет!", ())

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
    assert result == {"ok": True, "error": None, "result": "Привет!"}
    assert mcp.called is False
    assert llm.conversations[0][-1] == {"role": "user", "content": "hi"}
    assert "tool_results" not in result

    async def exercise() -> None:
        async_result = await agent.run_command_async("ещё")
        assert async_result == {"ok": True, "error": None, "result": "Привет!"}
        assert "tool_results" not in async_result

    asyncio.run(exercise())
    assert mcp.called is False
    assert llm.conversations[1][-1] == {"role": "user", "content": "ещё"}


def test_run_command_passes_history_to_llm():
    class RecordingLLM(LLMAsyncBridge):
        def __init__(self) -> None:
            self.conversations: list[list[dict[str, Any]]] = []

        def check_llm(self):
            return {"ok": True}

        def respond(self, conversation):
            self.conversations.append(list(conversation))
            return LLMResponse("Готово", ())

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
            return LLMResponse("готово", ())

    class PassiveMCP(MCPAsyncBridge):
        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            raise AssertionError("tool should not be invoked")

    llm = RecordingLLM()
    agent = LocalAgent(llm=llm, mcp=PassiveMCP())
    context_message = {"role": "system", "content": "Selected requirements (1): - SYS-1"}

    agent.run_command("выполни", context=context_message)
    assert llm.conversations[0][-2] == context_message
    assert llm.conversations[0][-1] == {"role": "user", "content": "выполни"}

    async def exercise() -> None:
        await agent.run_command_async(
            "повтори",
            context=[{"role": "system", "content": "Selected requirements: - SYS-2"}],
        )

    asyncio.run(exercise())
    assert llm.conversations[1][-2] == {
        "role": "system",
        "content": "Selected requirements: - SYS-2",
    }
    assert llm.conversations[1][-1] == {"role": "user", "content": "повтори"}


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
                            arguments={"rid": "SYS-1", "rev": 3},
                        ),
                    ),
                )
            return LLMResponse("Удалено", ())

        async def respond_async(self, conversation, *, cancellation=None):
            return self.respond(conversation)

    class StubMCP(MCPAsyncBridge):
        def __init__(self, settings, *, confirm):
            self.confirm = confirm

        def check_tools(self):
            return {"ok": True, "error": None}

        def call_tool(self, name, arguments):
            if name in {"delete_requirement", "patch_requirement"}:
                self.confirm("Delete requirement?")
            return {"ok": True, "error": None, "result": {}}

    monkeypatch.setattr(la, "LLMClient", StubLLM)
    monkeypatch.setattr(la, "MCPClient", StubMCP)
    agent = LocalAgent(settings=AppSettings(), confirm=custom_confirm)
    result = agent.run_command("remove")
    assert result["ok"] is True
    assert result["result"] == "Удалено"
    assert result.get("tool_results")
    assert result["tool_results"][0]["ok"] is True
    for tool_payload in result["tool_results"]:
        assert "tool_name" in tool_payload
        assert "tool_arguments" in tool_payload
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
            return LLMResponse("готово", ())

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
        assert result["result"] == "готово"
        assert result.get("tool_results")
        assert result["tool_results"][0]["ok"] is True
        for tool_payload in result["tool_results"]:
            assert "tool_name" in tool_payload
            assert "tool_arguments" in tool_payload

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
            return LLMResponse("готово", ())

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
        assert result["result"] == "готово"
        assert result.get("tool_results")
        assert result["tool_results"][0]["ok"] is True
        for tool_payload in result["tool_results"]:
            assert "tool_name" in tool_payload
            assert "tool_arguments" in tool_payload

    asyncio.run(exercise())

    assert llm.check_called is True
    assert llm.respond_called is True
    assert mcp.check_called is True
    assert mcp.call_called is True
