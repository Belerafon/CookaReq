"""Tests for local agent."""

import json

import httpx
import openai
import pytest

from app.agent import local_agent as la
from app.agent.local_agent import LocalAgent
from app.mcp.utils import ErrorCode
from app.settings import AppSettings

pytestmark = pytest.mark.integration


class FailingLLM:
    def check_llm(self):
        raise RuntimeError("llm failure")


class FailingMCP:
    def check_tools(self):
        raise RuntimeError("mcp failure")

    def call_tool(self, name, arguments):
        raise RuntimeError("call fail")


class DummyMCP:
    def call_tool(self, name, arguments):
        raise AssertionError("should not be called")


class DummyLLM:
    def parse_command(self, text: str):
        return "some_tool", {}


class JSONFailingLLM:
    def parse_command(self, text: str):
        raise json.JSONDecodeError("Expecting value", text, 0)


class OpenAINetworkLLM:
    def parse_command(self, text: str):
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
    agent = LocalAgent(llm=DummyLLM(), mcp=FailingMCP())
    with pytest.raises(RuntimeError, match="call fail"):
        agent.run_command("text")


def test_custom_confirm_message(monkeypatch):
    messages = []

    def custom_confirm(msg: str) -> bool:
        messages.append(msg)
        return True

    class StubLLM:
        def __init__(self, settings):
            pass

        def parse_command(self, text: str):
            return "delete_requirement", {}

    class StubMCP:
        def __init__(self, settings, *, confirm):
            self.confirm = confirm

        def call_tool(self, name, arguments):
            if name in {"delete_requirement", "patch_requirement"}:
                self.confirm("Delete requirement?")
            return {"ok": True, "error": None, "result": {}}

    monkeypatch.setattr(la, "LLMClient", StubLLM)
    monkeypatch.setattr(la, "MCPClient", StubMCP)
    agent = LocalAgent(settings=AppSettings(), confirm=custom_confirm)
    assert agent.run_command("remove") == {"ok": True, "error": None, "result": {}}
    assert messages == ["Delete requirement?"]
