"""Regression tests for preserving tool call arguments in ``LLMClient``."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

from openai.types.responses.response_function_tool_call import (
    ResponseFunctionToolCall,
)

from app.llm.client import LLMClient
from app.settings import LLMSettings


class _StringableArguments:
    def __init__(self, text: str) -> None:
        self._text = text

    def __str__(self) -> str:  # pragma: no cover - invoked by json.dumps
        return self._text


@dataclass(slots=True)
class _FakeFunction:
    name: str
    arguments: object


@dataclass(slots=True)
class _FakeToolCall:
    id: str
    function: _FakeFunction
    type: str = "function"


@dataclass(slots=True)
class _FakeMessage:
    tool_calls: list[_FakeToolCall]
    content: str | None = None


@dataclass(slots=True)
class _FakeChoice:
    message: _FakeMessage
    index: int = 0
    finish_reason: str | None = "tool_calls"


@dataclass(slots=True)
class _FakeCompletion:
    choices: list[_FakeChoice]


class _ModelDumpFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self._arguments = arguments

    def model_dump(self) -> Mapping[str, Any]:
        return {"name": self.name}

    @property
    def arguments(self) -> str:
        return self._arguments


class _ModelDumpToolCall:
    def __init__(self, call_id: str, function: _ModelDumpFunction) -> None:
        self.id = call_id
        self.function = function
        self.type = "function"

    def model_dump(self) -> Mapping[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "function": self.function.model_dump(),
        }


def test_llm_client_preserves_arguments_from_stringable_payload(monkeypatch) -> None:
    settings = LLMSettings()
    settings.base_url = "http://invalid"
    settings.api_key = "dummy"
    client = LLMClient(settings)

    payload = _StringableArguments(
        '{"rid":"DEMO8","field":"statement","value":"Перевести"}'
    )
    completion = _FakeCompletion(
        [
            _FakeChoice(
                message=_FakeMessage(
                    tool_calls=[
                        _FakeToolCall(
                            id="call-0",
                            function=_FakeFunction(
                                name="update_requirement_field",
                                arguments=payload,
                            ),
                        )
                    ]
                )
            )
        ]
    )

    monkeypatch.setattr(client, "_chat_completion", lambda **_: completion)

    response = client.respond([{"role": "user", "content": "translate DEMO8"}])

    assert response.tool_calls, "LLMClient should expose tool calls from completion"
    arguments = response.tool_calls[0].arguments
    assert arguments["rid"] == "DEMO8"
    assert arguments["field"] == "statement"
    assert arguments["value"] == "Перевести"


def test_llm_client_harmony_preserves_response_tool_arguments(monkeypatch) -> None:
    settings = LLMSettings()
    settings.base_url = "http://invalid"
    settings.api_key = "dummy"
    settings.message_format = "harmony"
    client = LLMClient(settings)

    class _HarmonyResponse:
        def __init__(self) -> None:
            self.output = [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Applying updates",
                        }
                    ],
                },
                ResponseFunctionToolCall(
                    id="resp-tool-1",
                    call_id="resp-tool-1",
                    name="update_requirement_field",
                    arguments=(
                        '{"rid":"DEMO11","field":"statement","value":"Готово"}'
                    ),
                    type="function_call",
                ),
            ]

    harmony_response = _HarmonyResponse()

    monkeypatch.setattr(
        client._client.responses,
        "create",
        lambda **_: harmony_response,
    )

    response = client.respond([
        {"role": "system", "content": "[Workspace context]"},
        {"role": "user", "content": "translate DEMO11"},
    ])

    assert response.tool_calls, "Harmony responses should expose tool calls"
    arguments = response.tool_calls[0].arguments
    assert arguments["rid"] == "DEMO11"
    assert arguments["field"] == "statement"
    assert arguments["value"] == "Готово"


def test_llm_client_recovers_arguments_when_model_dump_loses_them(monkeypatch) -> None:
    settings = LLMSettings()
    settings.base_url = "http://invalid"
    settings.api_key = "dummy"
    client = LLMClient(settings)

    tool_call = _ModelDumpToolCall(
        "call-3",
        _ModelDumpFunction(
            "update_requirement_field",
            '{"rid":"DEMO15","field":"title","value":"Русификация"}',
        ),
    )
    completion = _FakeCompletion(
        [
            _FakeChoice(
                message=_FakeMessage(
                    tool_calls=[tool_call],
                )
            )
        ]
    )

    monkeypatch.setattr(client, "_chat_completion", lambda **_: completion)

    response = client.respond([{"role": "user", "content": "translate DEMO15"}])

    assert response.tool_calls, "LLMClient should expose tool calls from completion"
    arguments = response.tool_calls[0].arguments
    assert arguments["rid"] == "DEMO15"
    assert arguments["field"] == "title"
    assert arguments["value"] == "Русификация"


def test_llm_client_streaming_combines_tool_call_chunks(monkeypatch) -> None:
    settings = LLMSettings()
    settings.base_url = "http://invalid"
    settings.api_key = "dummy"
    settings.stream = True
    client = LLMClient(settings)

    stream_chunks = [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "chunk-call-42",
                                "type": "function",
                                "function": {"name": "update_requirement_field"},
                            }
                        ]
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "chunk-call-42",
                                "type": "function",
                                "function": {
                                    "arguments": '{"rid":"DEMO21"',
                                },
                            }
                        ]
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "chunk-call-42",
                                "type": "function",
                                "function": {
                                    "arguments": ',"field":"statement"',
                                },
                            }
                        ]
                    },
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "id": "chunk-call-42",
                                "type": "function",
                                "function": {
                                    "arguments": ',"value":"Тест"}'
                                },
                            }
                        ],
                        "content": [
                            {"type": "output_text", "text": "Обновляю"}
                        ],
                    },
                }
            ]
        },
    ]

    monkeypatch.setattr(client, "_chat_completion", lambda **_: stream_chunks)

    response = client.respond([{"role": "user", "content": "update DEMO21"}])

    assert response.tool_calls, "Streaming client should produce tool calls"
    arguments = response.tool_calls[0].arguments
    assert arguments["rid"] == "DEMO21"
    assert arguments["field"] == "statement"
    assert arguments["value"] == "Тест"
