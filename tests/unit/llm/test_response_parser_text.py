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


def test_parse_chat_completion_extracts_think_blocks() -> None:
    parser = _parser()
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message={
                    "role": "assistant",
                    "content": "<think>Plan first.</think>Final answer.",
                }
            )
        ]
    )

    message, tool_calls, reasoning = parser.parse_chat_completion(completion)

    assert message == "Final answer."
    assert tool_calls == []
    assert reasoning == [
        {"type": "reasoning", "text": "Plan first."}
    ]


def test_parse_chat_completion_handles_multiple_think_blocks() -> None:
    parser = _parser()
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message={
                    "role": "assistant",
                    "content": "<think>First step.</think>\n<think>Second step.</think>Done",
                }
            )
        ]
    )

    message, tool_calls, reasoning = parser.parse_chat_completion(completion)

    assert message.strip() == "Done"
    assert tool_calls == []
    assert reasoning == [
        {"type": "reasoning", "text": "First step."},
        {"type": "reasoning", "text": "Second step."},
    ]


def test_finalize_reasoning_segments_merges_character_slices() -> None:
    parser = _parser()
    raw_segments = [
        {"type": "reasoning", "text": "Х"},
        {"type": "reasoning", "text": "оро"},
        {"type": "reasoning", "text": "шо"},
        {"type": "reasoning", "text": ","},
        {"type": "reasoning", "text": " давайте разберёмся."},
    ]

    result = parser.finalize_reasoning_segments(raw_segments)

    assert len(result) == 1
    segment = result[0]
    assert segment.type == "reasoning"
    assert segment.text == "Хорошо, давайте разберёмся."
    assert segment.leading_whitespace == ""
    assert segment.trailing_whitespace == ""


def test_finalize_reasoning_segments_preserves_edge_whitespace_when_merging() -> None:
    parser = _parser()
    raw_segments = [
        {"type": "analysis", "text": "Первый вывод", "trailing_whitespace": " \n"},
        {"type": "analysis", "text": "второй", "leading_whitespace": " "},
        {
            "type": "analysis",
            "text": "третий",
            "leading_whitespace": "\n",
            "trailing_whitespace": "  ",
        },
    ]

    result = parser.finalize_reasoning_segments(raw_segments)

    assert len(result) == 1
    segment = result[0]
    assert segment.type == "analysis"
    assert segment.text == "Первый вывод \n второй\nтретий"
    assert segment.leading_whitespace == ""
    assert segment.trailing_whitespace == "  "
