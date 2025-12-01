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
    sequence = diagnostic["llm_request_messages_sequence"]
    assert len(sequence) == 1
    assert sequence[0]["messages"] == request_messages
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


def test_build_entry_diagnostic_includes_llm_details():
    diagnostic = AgentChatPanel._build_entry_diagnostic(
        prompt="generate",
        prompt_at="2025-01-02T00:00:00Z",
        response_at="2025-01-02T00:00:05Z",
        display_response="validation error",
        stored_response="validation error",
        raw_result={
            "ok": False,
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Invalid arguments",
                "details": {
                    "type": "ToolValidationError",
                    "llm_message": "Preparing the requirement",
                    "llm_tool_calls": [
                        {
                            "id": "call-0",
                            "type": "function",
                            "function": {
                                "name": "create_requirement",
                                "arguments": "{\"prefix\": \"SYS\", \"data\": {\"title\": \"Req\"}}",
                            },
                        }
                    ],
                },
            },
        },
        tool_results=None,
        history_snapshot=None,
        context_snapshot=None,
    )

    assert diagnostic["llm_final_message"] == "Preparing the requirement"
    planned = diagnostic["llm_tool_calls"]
    assert isinstance(planned, list)
    assert planned
    assert planned[0]["function"]["name"] == "create_requirement"


def test_build_entry_diagnostic_prefers_logged_request_messages():
    diagnostic = AgentChatPanel._build_entry_diagnostic(
        prompt="generate",
        prompt_at="2025-01-03T00:00:00Z",
        response_at="2025-01-03T00:00:05Z",
        display_response="done",
        stored_response="done",
        raw_result={
            "ok": True,
            "result": "done",
            "diagnostic": {
                "llm_requests": [
                    {
                        "step": 1,
                        "messages": [
                            {"role": "system", "content": "merged system"},
                            {"role": "user", "content": "generate"},
                        ],
                    }
                ]
            },
        },
        tool_results=None,
        history_snapshot=[{"role": "system", "content": "legacy"}],
        context_snapshot=None,
    )

    request_messages = diagnostic["llm_request_messages"]
    assert request_messages[0]["content"] == "merged system"
    assert [msg["role"] for msg in request_messages].count("system") == 1
    sequence = diagnostic["llm_request_messages_sequence"]
    assert len(sequence) == 1
    assert sequence[0]["messages"] == request_messages
    assert diagnostic["llm_requests"] == sequence


def test_build_entry_diagnostic_falls_back_to_last_response_text():
    llm_trace = {
        "steps": [
            {
                "index": 1,
                "occurred_at": "2025-02-01T10:00:00Z",
                "request": [{"role": "user", "content": "hi"}],
                "response": {"content": "", "tool_calls": []},
            },
            {
                "index": 2,
                "occurred_at": "2025-02-01T10:00:05Z",
                "request": [{"role": "user", "content": "hi"}],
                "response": {
                    "content": "LLM reasoning text",
                    "tool_calls": [],
                },
            },
        ]
    }

    diagnostic = AgentChatPanel._build_entry_diagnostic(
        prompt="hi",
        prompt_at=None,
        response_at=None,
        display_response="",
        stored_response="",
        raw_result={
            "ok": False,
            "status": "failed",
            "result": "",
            "llm_trace": llm_trace,
            "reasoning": [],
        },
        tool_results=None,
        history_snapshot=None,
        context_snapshot=None,
    )

    assert diagnostic["llm_final_message"] == "LLM reasoning text"


def test_build_entry_diagnostic_preserves_request_sequence_metadata():
    diagnostic = AgentChatPanel._build_entry_diagnostic(
        prompt="iterate",
        prompt_at="2025-01-04T00:00:00Z",
        response_at="2025-01-04T00:00:05Z",
        display_response="done",
        stored_response="done",
        raw_result={
            "ok": True,
            "result": "done",
            "diagnostic": {
                "llm_requests": [
                    {"step": "1", "messages": [{"role": "user", "content": "first"}]},
                    {
                        "step": 2,
                        "messages": [
                            {"role": "assistant", "content": "final"}
                        ],
                        "extra": {"note": "metadata"},
                    },
                ],
            },
        },
        tool_results=None,
        history_snapshot=None,
        context_snapshot=None,
    )

    sequence = diagnostic["llm_request_messages_sequence"]
    assert len(sequence) == 2
    assert sequence[0]["step"] == 1
    assert sequence[0]["messages"][0]["content"] == "first"
    assert sequence[1]["messages"][0]["content"] == "final"
    assert "extra" not in sequence[1]
    assert diagnostic["llm_request_messages"][0]["content"] == "final"
    assert diagnostic["llm_requests"] == sequence
