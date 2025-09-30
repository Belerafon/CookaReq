from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.llm.response_parser import LLMResponseParser, StreamConsumptionError
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


def test_consume_stream_uses_message_fallback_from_choice_message():
    parser = _parser()
    stream = [
        {
            "choices": [
                {
                    "delta": {},
                    "message": {"assistant": "Translation output"},
                }
            ]
        }
    ]

    message, tool_calls, reasoning = parser.consume_stream(stream, cancellation=None)

    assert message == "Translation output"
    assert tool_calls == []
    assert reasoning == []


def test_consume_stream_uses_message_fallback_from_nested_segments():
    parser = _parser()
    stream = [
        {
            "choices": [
                {
                    "delta": {},
                    "message": {
                        "content": [
                            {"type": "output_text", "text": "Line 1"},
                            {"type": "output_text", "text": " and Line 2"},
                        ]
                    },
                }
            ]
        }
    ]

    message, tool_calls, reasoning = parser.consume_stream(stream, cancellation=None)

    assert message == "Line 1 and Line 2"
    assert tool_calls == []
    assert reasoning == []


def test_consume_stream_raises_error_with_partial_payload():
    parser = _parser()

    class BrokenStream:
        def __iter__(self):
            yield {
                "choices": [
                    {
                        "delta": {},
                        "message": {"assistant": "Finished text"},
                    }
                ]
            }
            raise RuntimeError("stream closed unexpectedly")

        def close(self):
            self.closed = True  # pragma: no cover - diagnostic

    stream = BrokenStream()

    with pytest.raises(StreamConsumptionError) as excinfo:
        parser.consume_stream(stream, cancellation=None)

    assert excinfo.value.message_text == "Finished text"
    assert excinfo.value.raw_tool_calls_payload == []
    assert excinfo.value.reasoning_segments == []


def test_consume_stream_collects_output_text_delta_segments():
    parser = _parser()
    stream = [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "content": [
                            {"type": "output_text", "text": "First"},
                            {"type": "message", "text": " part"},
                        ]
                    },
                }
            ]
        }
    ]

    message, tool_calls, reasoning = parser.consume_stream(stream, cancellation=None)

    assert message == "First part"
    assert tool_calls == []
    assert reasoning == []


def test_consume_stream_collects_plain_string_chunks():
    parser = _parser()
    stream = [
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "Hello"},
                }
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": " world"},
                }
            ]
        },
    ]

    message, tool_calls, reasoning = parser.consume_stream(stream, cancellation=None)

    assert message == "Hello world"
    assert tool_calls == []
    assert reasoning == []
