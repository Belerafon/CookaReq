"""Focused tests for extracting text from LLM responses."""

from types import SimpleNamespace

from app.llm.response_parser import LLMResponseParser
from app.settings import LLMSettings


def _parser() -> LLMResponseParser:
    settings = LLMSettings()
    return LLMResponseParser(settings, settings.message_format)


def test_parse_chat_completion_uses_message_assistant_field() -> None:
    parser = _parser()
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message={
                    "content": None,
                    "assistant": "Перевод готов",
                }
            )
        ]
    )

    message, tool_calls, reasoning = parser.parse_chat_completion(completion)

    assert message == "Перевод готов"
    assert tool_calls == []
    assert reasoning == []


def test_consume_stream_recovers_message_assistant_text() -> None:
    parser = _parser()
    stream = [
        {
            "choices": [
                {
                    "delta": {},
                    "message": {"assistant": "Stream result"},
                }
            ]
        }
    ]

    message, tool_calls, reasoning = parser.consume_stream(stream, cancellation=None)

    assert message == "Stream result"
    assert tool_calls == []
    assert reasoning == []
