from __future__ import annotations

from app.util.text_inspect import (
    TextUnstableReason,
    classify_unstable_text,
    is_unstable_text,
)


def test_classify_unstable_text_detects_pointer_repr() -> None:
    text = "<Sample object at 0xabc123>"

    assert classify_unstable_text(text) == TextUnstableReason.POINTER_REPR


def test_classify_unstable_text_detects_massive_dumps() -> None:
    text = "\n".join(f"line {index}" for index in range(500))

    assert classify_unstable_text(text) == TextUnstableReason.MASSIVE_DUMP


def test_is_unstable_text_handles_binary_noise() -> None:
    blob = "\x00" * 20 + "text"

    assert is_unstable_text(blob)
