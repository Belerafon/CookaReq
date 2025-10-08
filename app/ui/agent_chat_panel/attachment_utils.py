"""Helpers for validating chat attachments."""
from __future__ import annotations

from collections.abc import Iterable

_ALLOWED_TEXT_CONTROLS = frozenset({"\n", "\r", "\t", "\f", "\b", "\x1b"})
_SAMPLE_LIMIT = 8192


def looks_like_plain_text(
    text: str,
    *,
    sample_limit: int = _SAMPLE_LIMIT,
    allowed_controls: Iterable[str] | None = None,
) -> bool:
    """Heuristically determine whether ``text`` represents plain UTF-8 content."""
    if not text:
        return True

    controls = _ALLOWED_TEXT_CONTROLS if allowed_controls is None else frozenset(allowed_controls)
    sample = text[:sample_limit]

    if "\x00" in sample:
        return False

    suspicious = 0
    threshold = max(1, len(sample) // 200)

    for ch in sample:
        code = ord(ch)
        if (code < 32 or code == 127) and ch not in controls:
            suspicious += 1
            if suspicious > threshold:
                return False

    return True


__all__ = ["looks_like_plain_text"]
