"""Tests for mcp text commands."""

import json
import logging
from http.client import HTTPConnection
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent import LocalAgent
from app.core.document_store import Document, save_document, save_item
from app.core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
    requirement_to_dict,
)
from app.log import logger
from app.mcp.server import JsonlHandler
from app.mcp.server import app as mcp_app
from app.mcp.utils import ErrorCode
from tests.llm_utils import make_openai_mock, settings_with_mcp

pytestmark = pytest.mark.integration


def test_run_command_list_logs(tmp_path: Path, monkeypatch, mcp_server) -> None:
    port = mcp_server
    mcp_app.state.base_path = str(tmp_path)
    settings = settings_with_mcp(
        "127.0.0.1",
        port,
        str(tmp_path),
        "",
        tmp_path=tmp_path,
    )
    # Мокаем OpenAI, чтобы исключить внешние вызовы.
    monkeypatch.setattr(
        "openai.OpenAI",
        make_openai_mock(
            {
                "list requirements per page 1": [
                    ("list_requirements", {"per_page": 1}),
                    {"message": "Готово"},
                ]
            },
        ),
    )
    client = LocalAgent(settings=settings, confirm=lambda _m: True)
    log_file = tmp_path / "cmd.jsonl"
    handler = JsonlHandler(str(log_file))
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        result = client.run_command("list requirements per page 1")
    finally:
        logger.setLevel(prev_level)
        logger.removeHandler(handler)
    assert result["ok"] is True
    assert result.get("tool_results")
    assert result["result"] == "Готово"
    assert result["tool_results"][0]["result"]["items"] == []
    entries = [json.loads(line) for line in log_file.read_text().splitlines()]
    events = {e.get("event") for e in entries}
    assert {"LLM_REQUEST", "LLM_RESPONSE", "TOOL_CALL", "TOOL_RESULT", "DONE"} <= events


def test_run_command_error_logs(tmp_path: Path, monkeypatch, mcp_server) -> None:
    port = mcp_server
    mcp_app.state.base_path = str(tmp_path)
    settings = settings_with_mcp(
        "127.0.0.1",
        port,
        str(tmp_path),
        "",
        tmp_path=tmp_path,
    )
    # Мокаем OpenAI, чтобы исключить внешние вызовы.
    monkeypatch.setattr(
        "openai.OpenAI",
        make_openai_mock({"get requirement SYS1": ("get_requirement", {"rid": "SYS1"})}),
    )
    client = LocalAgent(settings=settings, confirm=lambda _m: True)
    log_file = tmp_path / "err.jsonl"
    handler = JsonlHandler(str(log_file))
    logger.addHandler(handler)
    prev_level = logger.level
    logger.setLevel(logging.INFO)
    try:
        result = client.run_command("get requirement SYS1")
    finally:
        logger.setLevel(prev_level)
        logger.removeHandler(handler)
    assert result["ok"] is False
    entries = [json.loads(line) for line in log_file.read_text().splitlines()]
    events = {e.get("event") for e in entries}
    assert {
        "LLM_REQUEST",
        "LLM_RESPONSE",
        "TOOL_CALL",
        "TOOL_RESULT",
        "ERROR",
    } <= events


def test_run_command_fetches_requirement_with_prefixed_rid(
    tmp_path: Path, monkeypatch, mcp_server
) -> None:
    port = mcp_server
    mcp_app.state.base_path = str(tmp_path)
    settings = settings_with_mcp(
        "127.0.0.1",
        port,
        str(tmp_path),
        "",
        tmp_path=tmp_path,
    )

    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=11,
        title="Первое требование",
        statement="Содержимое первого требования.",
        type=RequirementType.REQUIREMENT,
        status=Status.APPROVED,
        owner="owner",
        priority=Priority.MEDIUM,
        source="specification",
        verification=Verification.ANALYSIS,
    )
    save_item(doc_dir, doc, requirement_to_dict(requirement))

    responses = {
        "Напиши текст первого требования": [
            ("get_requirement", {"rid": "SYS11"}),
            {"message": "Текст требования: Содержимое первого требования."},
        ]
    }
    prepared: dict[str, list[Any]] = {
        key: list(value) if isinstance(value, list) else [value]
        for key, value in responses.items()
    }
    captured_messages: list[list[dict[str, Any]]] = []

    class RecordingCompletions:
        def create(self, *, messages, tools=None, **kwargs):
            captured_messages.append(messages)
            user_prompt = next(
                (
                    msg.get("content")
                    for msg in reversed(messages)
                    if msg.get("role") == "user"
                ),
                messages[-1].get("content"),
            )
            queue = prepared.get(user_prompt)
            if queue is None:
                queue = prepared.setdefault(user_prompt, [("list_requirements", {})])
            result = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(result, tuple):
                name, args = result
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                tool_calls=[
                                    SimpleNamespace(
                                        id="call-1",
                                        function=SimpleNamespace(
                                            name=name,
                                            arguments=json.dumps(args),
                                        ),
                                    )
                                ],
                                content=None,
                            )
                        )
                    ]
                )
            if isinstance(result, dict) and "message" in result:
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=result["message"],
                                tool_calls=None,
                            )
                        )
                    ]
                )
            raise AssertionError(f"Unexpected mock response: {result!r}")

    class RecordingChat:
        def __init__(self) -> None:
            self.completions = RecordingCompletions()

    class RecordingOpenAI:
        def __init__(self, *args, **kwargs) -> None:
            self.chat = RecordingChat()

    monkeypatch.setattr("openai.OpenAI", RecordingOpenAI)

    client = LocalAgent(settings=settings, confirm=lambda _m: True)
    context = [
        {
            "role": "system",
            "content": (
                "[Workspace context]\n"
                "Active requirements list: SYS: Сист. треб.\n"
                "Selected requirements (1):\n"
                "- SYS11 — Содержимое первого требования."
            ),
        }
    ]
    result = client.run_command(
        "Напиши текст первого требования",
        context=context,
    )

    assert result["ok"] is True, result
    assert result["error"] is None
    assert result["result"] == "Текст требования: Содержимое первого требования."
    tool_results = result.get("tool_results")
    assert isinstance(tool_results, list) and tool_results
    first_tool = tool_results[0]
    assert first_tool["tool_name"] == "get_requirement"
    assert first_tool["tool_arguments"]["rid"] == "SYS11"
    assert first_tool["result"]["rid"] == "SYS11"
    assert first_tool["result"]["statement"] == "Содержимое первого требования."

    assert captured_messages, "LLM mock should capture at least one request"
    system_prompt = captured_messages[0][0]["content"]
    assert "<prefix><number>" in system_prompt
    assert "SYS11 — Содержимое первого требования." in system_prompt


def test_mcp_endpoint_direct_call(tmp_path: Path, mcp_server) -> None:
    port = mcp_server
    mcp_app.state.base_path = str(tmp_path)
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(
            "POST",
            "/mcp",
            body=json.dumps({"name": "list_requirements", "arguments": {"per_page": 1}}),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        body = resp.read().decode()
    finally:
        conn.close()
    assert resp.status == 200
    payload = json.loads(body)
    assert payload["items"] == []


def test_mcp_endpoint_unknown_tool(tmp_path: Path, mcp_server) -> None:
    port = mcp_server
    mcp_app.state.base_path = str(tmp_path)
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(
            "POST",
            "/mcp",
            body=json.dumps({"name": "unknown_tool", "arguments": {}}),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        body = resp.read().decode()
    finally:
        conn.close()
    assert resp.status == 404
    payload = json.loads(body)
    assert payload["error"]["code"] == ErrorCode.NOT_FOUND.value
