"""Regression tests for preserving tool call arguments in ``LLMClient``."""

from __future__ import annotations

from dataclasses import dataclass

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
