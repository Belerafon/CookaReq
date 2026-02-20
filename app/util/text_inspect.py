"""Heuristics for classifying unstable textual representations."""
from __future__ import annotations

from enum import StrEnum
import re
from collections.abc import Iterable

__all__ = [
    "TextUnstableReason",
    "classify_unstable_text",
    "is_unstable_text",
]


class TextUnstableReason(StrEnum):
    """Reasons that make a textual representation unsuitable for reuse."""

    POINTER_REPR = "pointer-repr"
    MASSIVE_DUMP = "massive-dump"
    BINARY_NOISE = "binary-noise"


_POINTER_RE = re.compile(r"<[^>]+ object at 0x[0-9a-f]+>", re.IGNORECASE)


def _looks_like_pointer_repr(text: str) -> bool:
    lowered = text.lower()
    if " object at 0x" in lowered:
        return True
    return bool(_POINTER_RE.search(text))


def _split_lines_sample(text: str, limit: int) -> Iterable[str]:
    count = 0
    start = 0
    length = len(text)
    while start < length and count < limit:
        end = text.find("\n", start)
        if end == -1:
            yield text[start:]
            return
        yield text[start:end]
        start = end + 1
        count += 1


def classify_unstable_text(
    text: str,
    *,
    detect_pointer_repr: bool = True,
    detect_massive_dumps: bool = True,
    detect_binary_noise: bool = True,
    min_dump_length: int = 4096,
    max_line_count: int = 400,
    max_line_length: int = 2000,
    binary_ratio_threshold: float = 0.1,
) -> TextUnstableReason | None:
    """Return instability reason for *text* or ``None`` when it looks safe."""
    if not text:
        return None

    if detect_pointer_repr and _looks_like_pointer_repr(text):
        return TextUnstableReason.POINTER_REPR

    if detect_massive_dumps and len(text) >= max(0, min_dump_length):
        newline_count = text.count("\n") + text.count("\r")
        if newline_count >= max_line_count:
            return TextUnstableReason.MASSIVE_DUMP
        for line in _split_lines_sample(text, max_line_count):
            if len(line) > max_line_length:
                return TextUnstableReason.MASSIVE_DUMP

    if detect_binary_noise and binary_ratio_threshold > 0:
        control = sum(1 for char in text if ord(char) < 32 and char not in "\t\r\n")
        if control and control / len(text) >= binary_ratio_threshold:
            return TextUnstableReason.BINARY_NOISE

    return None


def is_unstable_text(text: str, **kwargs: object) -> bool:
    """Return ``True`` when :func:`classify_unstable_text` detects an issue."""
    return classify_unstable_text(text, **kwargs) is not None
