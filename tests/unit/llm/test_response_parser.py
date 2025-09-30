from __future__ import annotations

from types import SimpleNamespace

from app.llm.response_parser import LLMResponseParser
from app.settings import LLMSettings


def _parser() -> LLMResponseParser:
    settings = LLMSettings()
    return LLMResponseParser(settings, settings.message_format)


def test_parse_chat_completion_handles_plain_string_message():
    parser = _parser()
    completion = SimpleNamespace(choices=[SimpleNamespace(message="Translated text")])

    message, tool_calls, reasoning = parser.parse_chat_completion(completion)

    assert message == "Translated text"
    assert tool_calls == []
    assert reasoning == []


def test_parse_chat_completion_falls_back_to_top_level_text():
    parser = _parser()
    completion = SimpleNamespace(
        assistant="Resolved translation",
        choices=[SimpleNamespace(message=SimpleNamespace(content=None))],
    )

    message, tool_calls, reasoning = parser.parse_chat_completion(completion)

    assert message == "Resolved translation"
    assert tool_calls == []
    assert reasoning == []
