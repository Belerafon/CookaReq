import pytest

from app.ui.agent_chat_panel import AgentChatPanel


pytestmark = pytest.mark.core


def test_build_entry_diagnostic_includes_tool_results():
    diagnostic = AgentChatPanel._build_entry_diagnostic(
        prompt="generate report",
        prompt_at="2025-01-01T10:00:00Z",
        response_at="2025-01-01T10:00:05Z",
        display_response="done",
        stored_response="done",
        raw_result={"ok": True, "result": "done"},
        tool_results=[
            {
                "tool_name": "demo_tool",
                "ok": True,
                "tool_arguments": {"query": "generate report"},
                "result": {"status": "ok"},
            }
        ],
        history_snapshot=[{"role": "user", "content": "previous"}],
        context_snapshot=None,
    )

    assert isinstance(diagnostic, dict)
    request_messages = diagnostic["llm_request_messages"]
    assert request_messages[0]["role"] == "system"
    assert request_messages[-1]["role"] == "user"
    assert diagnostic["tool_exchanges"][0]["tool_name"] == "demo_tool"


def test_build_entry_diagnostic_falls_back_to_raw_result_payload():
    diagnostic = AgentChatPanel._build_entry_diagnostic(
        prompt="create",
        prompt_at="2025-01-01T11:00:00Z",
        response_at="2025-01-01T11:00:02Z",
        display_response="validation failed",
        stored_response="validation failed",
        raw_result={
            "tool_name": "create_requirement",
            "tool_call_id": "call-1",
            "ok": False,
            "error": {"code": "VALIDATION_ERROR"},
            "tool_arguments": {"data": {"title": "Req"}},
        },
        tool_results=None,
        history_snapshot=[],
        context_snapshot=None,
    )

    exchanges = diagnostic["tool_exchanges"]
    assert exchanges and exchanges[0]["tool_name"] == "create_requirement"
    assert exchanges[0]["tool_arguments"]["data"]["title"] == "Req"


def test_build_entry_diagnostic_omits_duplicate_stored_response():
    diagnostic = AgentChatPanel._build_entry_diagnostic(
        prompt="status",
        prompt_at=None,
        response_at=None,
        display_response="all good",
        stored_response="all good",
        raw_result={"ok": True, "result": "all good"},
        tool_results=None,
        history_snapshot=None,
        context_snapshot=None,
    )

    assert diagnostic["agent_stored_response"] is None
