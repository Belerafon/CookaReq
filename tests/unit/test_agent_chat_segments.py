"""Unit tests for agent chat segment helpers."""

from __future__ import annotations

from app.ui.agent_chat_panel.components.segments import _format_reasoning_segments


def test_format_reasoning_segments_merges_consecutive_chunks() -> None:
    segments = [
        {"type": "reasoning", "text": "User"},
        {"type": "reasoning", "text": " request"},
        {"type": "analysis", "text": "Next step"},
    ]

    value = _format_reasoning_segments(segments)

    assert value.count("reasoning") == 1
    assert "User request" in value
    assert "analysis\nNext step" in value


def test_format_reasoning_segments_preserves_in_word_streaming() -> None:
    segments = [
        {"type": "reasoning", "text": "пользоват"},
        {"type": "reasoning", "text": "ель "},
        {"type": "reasoning", "text": "прос"},
        {"type": "reasoning", "text": "ит"},
        {"type": "reasoning", "text": " перевести"},
    ]

    value = _format_reasoning_segments(segments)

    assert "reasoning\nпользователь просит перевести" in value
