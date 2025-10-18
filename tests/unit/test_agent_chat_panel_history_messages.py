import json

from app.ui.agent_chat_panel.panel import AgentChatPanel
from app.ui.chat_entry import ChatEntry


def _make_tool_message(call_id: str, name: str = "demo_tool", content: str = "{}") -> dict[str, str]:
    return {"role": "tool", "content": content, "tool_call_id": call_id, "name": name}


def test_entry_conversation_messages_include_tool_calls() -> None:
    entry = ChatEntry(
        prompt="Update",
        response="All done",
        tokens=0,
        diagnostic={
            "llm_steps": [
                {
                    "step": 1,
                    "response": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "name": "demo_tool",
                                "arguments": {"rid": "REQ-1"},
                            }
                        ],
                    },
                }
            ]
        },
        tool_messages=(
            _make_tool_message(
                "call-1",
                content=json.dumps({"ok": True, "tool_call_id": "call-1"}, ensure_ascii=False),
            ),
        ),
    )

    messages = AgentChatPanel._entry_conversation_messages(entry)

    assert len(messages) == 3
    first = messages[0]
    assert first["role"] == "assistant"
    tool_calls = first.get("tool_calls")
    assert isinstance(tool_calls, list) and tool_calls
    call_payload = tool_calls[0]
    assert call_payload["id"] == "call-1"
    assert call_payload["function"]["name"] == "demo_tool"
    assert json.loads(call_payload["function"]["arguments"]) == {"rid": "REQ-1"}
    assert messages[1]["role"] == "tool"
    assert messages[1]["tool_call_id"] == "call-1"
    assert messages[2]["role"] == "assistant"
    assert messages[2]["content"] == "All done"


def test_entry_conversation_messages_without_diagnostic_falls_back() -> None:
    entry = ChatEntry(
        prompt="Check",
        response="Result text",
        tokens=0,
        tool_messages=(
            _make_tool_message("orphan", content=json.dumps({"ok": True}, ensure_ascii=False)),
        ),
    )

    messages = AgentChatPanel._entry_conversation_messages(entry)

    assert len(messages) == 2
    assert messages[0]["role"] == "assistant"
    assert messages[0]["content"] == "Result text"
    assert messages[1]["role"] == "tool"
    assert messages[1]["tool_call_id"] == "orphan"


def test_entry_conversation_messages_preserve_final_response_only_once() -> None:
    entry = ChatEntry(
        prompt="Summarize",
        response="Summary text",
        tokens=0,
        diagnostic={
            "llm_steps": [
                {
                    "step": 1,
                    "response": {
                        "content": "Summary text",
                    },
                }
            ]
        },
    )

    messages = AgentChatPanel._entry_conversation_messages(entry)

    assistant_messages = [m for m in messages if m["role"] == "assistant"]
    assert len(assistant_messages) == 1
    assert assistant_messages[0]["content"] == "Summary text"
