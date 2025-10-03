"""Unit tests for agent chat segment helpers."""

from __future__ import annotations

from app.ui.agent_chat_panel.panel import format_reasoning_segments_plain


def test_format_reasoning_segments_merges_consecutive_chunks() -> None:
    segments = [
        {"type": "reasoning", "text": "User", "trailing_whitespace": " "},
        {"type": "reasoning", "text": "request"},
        {"type": "analysis", "text": "Next step"},
    ]

    value = format_reasoning_segments_plain(segments)

    assert value.count("reasoning") == 1
    assert "User request" in value
    assert "analysis\nNext step" in value


def test_format_reasoning_segments_preserves_in_word_streaming() -> None:
    segments = [
        {"type": "reasoning", "text": "пользоват"},
        {"type": "reasoning", "text": "ель", "trailing_whitespace": " "},
        {"type": "reasoning", "text": "прос"},
        {"type": "reasoning", "text": "ит"},
        {"type": "reasoning", "text": "перевести", "leading_whitespace": " "},
    ]

    value = format_reasoning_segments_plain(segments)

    assert "reasoning\nпользователь просит перевести" in value


def test_format_reasoning_segments_reinstates_leading_space() -> None:
    segments = [
        {"type": "reasoning", "text": "First"},
        {"type": "reasoning", "text": "second", "leading_whitespace": " "},
    ]

    value = format_reasoning_segments_plain(segments)

    assert "First second" in value
