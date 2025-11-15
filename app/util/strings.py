"""String helpers with defensive conversions."""

from __future__ import annotations

from typing import Any, Iterable, Callable

__all__ = ["coerce_text"]


def coerce_text(
    value: Any,
    *,
    allow_empty: bool = False,
    fallback: str | None = None,
    converters: Iterable[Callable[[Any], str]] | None = None,
) -> str | None:
    """Return a textual representation of ``value`` resilient to bad ``__str__``.

    The function tries each converter in ``converters`` (defaults to ``str`` and
    ``repr``) until one returns a non-empty string. When ``allow_empty`` is
    ``True`` the first successful conversion is returned even if it yields an
    empty string. If every converter fails and ``fallback`` is provided it is
    returned instead; otherwise ``None`` is returned.
    """

    if converters is None:
        converters = (str, repr)

    for converter in converters:
        try:
            text = converter(value)
        except Exception:
            continue
        if not isinstance(text, str):
            continue
        if text or allow_empty:
            return text

    if fallback is not None:
        return fallback

    return None
