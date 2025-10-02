"""Tests for reasoning normalisation helpers."""

from __future__ import annotations

from app.llm.reasoning import normalise_reasoning_segments
from app.llm.types import LLMReasoningSegment
from app.llm.utils import extract_mapping


def test_extract_mapping_handles_dataclass_with_slots() -> None:
    segment = LLMReasoningSegment(type="analysis", text="value")
    mapping = extract_mapping(segment)
    assert mapping == {
        "type": "analysis",
        "text": "value",
        "leading_whitespace": "",
        "trailing_whitespace": "",
    }


def test_reasoning_segment_preview_preserves_whitespace() -> None:
    segment = LLMReasoningSegment(
        type="analysis",
        text="value",
        leading_whitespace=" ",
        trailing_whitespace="  ",
    )

    assert segment.text_with_whitespace == " value  "
    assert segment.preview() == " value  "
    assert segment.preview(3) == " va"


def test_normalise_reasoning_segments_from_dataclasses() -> None:
    segments = (
        LLMReasoningSegment(type="analysis", text="  Evaluate path  "),
        LLMReasoningSegment(type="reasoning", text=""),
        LLMReasoningSegment(type="thinking", text="Consider next step"),
    )

    result = normalise_reasoning_segments(segments)

    assert result == [
        {
            "type": "analysis",
            "text": "Evaluate path",
            "leading_whitespace": "  ",
            "trailing_whitespace": "  ",
        },
        {"type": "thinking", "text": "Consider next step"},
    ]


def test_normalise_reasoning_segments_from_nested_payload() -> None:
    payload = [
        {"type": "analysis", "text": "First stage"},
        {
            "type": "analysis",
            "content": [
                {"type": "thought", "text": "   Trim me   "},
                {"text": "Assume default type"},
            ],
        },
        "",
    ]

    result = normalise_reasoning_segments(payload)

    assert result == [
        {"type": "analysis", "text": "First stage"},
        {
            "type": "thought",
            "text": "Trim me",
            "leading_whitespace": "   ",
            "trailing_whitespace": "   ",
        },
        {"type": "reasoning", "text": "Assume default type"},
    ]


def test_normalise_reasoning_segments_merges_adjacent_fragments() -> None:
    payload = [
        {"type": "reasoning", "text": "Х"},
        {"type": "reasoning", "text": "оро"},
        {"type": "reasoning", "text": "шо"},
        {"type": "reasoning", "text": ","},
        {"type": "reasoning", "text": " давайте разберёмся."},
    ]

    result = normalise_reasoning_segments(payload)

    assert result == [
        {
            "type": "reasoning",
            "text": "Хорошо, давайте разберёмся.",
        }
    ]
