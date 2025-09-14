"""Tests for local agent."""

import pytest

from app.agent import local_agent as la
from app.agent.local_agent import LocalAgent
from app.settings import AppSettings
from app.mcp.utils import ErrorCode


class FailingLLM:
    def check_llm(self):
        raise RuntimeError("llm failure")

    def parse_command(self, text: str):
        raise RuntimeError("parse fail")


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



def test_check_llm_and_check_tools_propagate_errors():
    agent = LocalAgent(llm=FailingLLM(), mcp=FailingMCP())
    with pytest.raises(RuntimeError, match="llm failure"):
        agent.check_llm()
    with pytest.raises(RuntimeError, match="mcp failure"):
        agent.check_tools()


def test_run_command_handles_llm_error():
    agent = LocalAgent(llm=FailingLLM(), mcp=DummyMCP())
    result = agent.run_command("whatever")
    assert result["error"]["code"] == ErrorCode.VALIDATION_ERROR
    assert result["error"]["message"] == "parse fail"


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
            return {"ok": True}

    monkeypatch.setattr(la, "LLMClient", StubLLM)
    monkeypatch.setattr(la, "MCPClient", StubMCP)
    agent = LocalAgent(settings=AppSettings(), confirm=custom_confirm)
    assert agent.run_command("remove") == {"ok": True}
    assert messages == ["Delete requirement?"]
