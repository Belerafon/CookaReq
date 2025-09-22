"""Unit tests for agent transcript logging helpers."""

from __future__ import annotations

import pytest

from app.ui.agent_chat_panel import _collect_tool_payloads
from app.ui.chat_entry import ChatEntry


pytestmark = pytest.mark.core


def make_entry(**kwargs):
    defaults = {
        "prompt": "user", 
        "response": "", 
        "tokens": 0,
    }
    defaults.update(kwargs)
    return ChatEntry(**defaults)


def test_collect_tool_payloads_prefers_explicit_tool_results():
    payload = {"tool_name": "list_requirements", "tool_arguments": {"page": 1}}
    entry = make_entry(tool_results=[payload], raw_result={"ok": True})

    result = _collect_tool_payloads(entry)

    assert result == [payload]


def test_collect_tool_payloads_extracts_from_raw_result_when_missing():
    raw_payload = {
        "tool_name": "create_requirement",
        "tool_call_id": "abc",
        "ok": False,
        "error": {"code": "VALIDATION_ERROR"},
        "tool_arguments": {
            "prefix": "sys",
            "data": {
                "title": "Req",
                "statement": "Do it",
            },
        },
    }
    entry = make_entry(raw_result=raw_payload, tool_results=None)

    result = _collect_tool_payloads(entry)

    assert result and result[0]["tool_name"] == "create_requirement"
    assert result[0]["tool_arguments"]["data"]["title"] == "Req"


def test_collect_tool_payloads_converts_non_json_sequences():
    raw_payload = {
        "tool_name": "create_requirement",
        "tool_arguments": {
            "labels": ("draft", "ui"),
        },
    }
    entry = make_entry(raw_result=raw_payload, tool_results=None)

    result = _collect_tool_payloads(entry)

    assert result and result[0]["tool_arguments"]["labels"] == ["draft", "ui"]


def test_collect_tool_payloads_ignores_non_tool_payloads():
    entry = make_entry(raw_result={"ok": True, "result": "done"}, tool_results=None)

    result = _collect_tool_payloads(entry)

    assert result == []
