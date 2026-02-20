"""String helpers with defensive conversions."""
from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

__all__ = ["coerce_text", "describe_unprintable", "truncate_text"]

_DEFAULT_CONVERTERS: tuple[Callable[[Any], object], ...] = (str, repr)


def _normalise_candidate(candidate: object) -> str | None:
    """Convert ``candidate`` into a usable string when possible."""
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, (bytes, bytearray)):
        raw = bytes(candidate)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")
    return None


def truncate_text(text: str, limit: int | None) -> str:
    """Clip ``text`` to ``limit`` characters using an ellipsis when required."""
    if limit is None or limit <= 0 or len(text) <= limit:
        return text
    if limit == 1:
        return "…"
    return f"{text[: limit - 1]}…"


def describe_unprintable(value: Any, *, prefix: str = "unprintable") -> str:
    """Return a placeholder describing ``value`` that resisted stringification."""
    cls = type(value)
    qualname = getattr(cls, "__qualname__", cls.__name__)
    module = getattr(cls, "__module__", "")
    typename = f"{module}.{qualname}" if module and module != "builtins" else qualname
    if prefix:
        return f"<{prefix} {typename}>"
    return f"<{typename}>"


def coerce_text(
    value: Any,
    *,
    allow_empty: bool = False,
    fallback: str | None = None,
    fallback_factory: Callable[[Any], str | None] | None = None,
    converters: Iterable[Callable[[Any], object]] | None = None,
    normaliser: Callable[[object], str | None] | None = None,
    truncate: int | None = None,
) -> str | None:
    """Return a textual representation of ``value`` resilient to bad ``__str__``.

    The function iterates over the provided ``converters`` (defaults to ``str``
    and ``repr``). Each candidate is passed through ``normaliser`` which can
    turn non-string outputs such as ``bytes`` into ``str``. Conversions raising
    exceptions are ignored. When all converters fail the explicit ``fallback``
    is returned, otherwise the ``fallback_factory`` is invoked. Both fallbacks
    honour ``allow_empty`` and ``truncate``. ``None`` is returned only when no
    conversion succeeded and no fallback produced a usable string.
    """
    converter_sequence: Iterable[Callable[[Any], object]]
    converter_sequence = _DEFAULT_CONVERTERS if converters is None else converters

    text_normaliser = normaliser or _normalise_candidate

    direct = text_normaliser(value)
    if direct is not None and (direct or allow_empty):
        return truncate_text(direct, truncate)

    for converter in converter_sequence:
        try:
            candidate = converter(value)
        except Exception:
            continue
        text = text_normaliser(candidate)
        if text is None:
            continue
        if text or allow_empty:
            return truncate_text(text, truncate)

    def _coerce_fallback(result: object | None) -> str | None:
        if result is None:
            return None
        text = text_normaliser(result)
        if text is None:
            return None
        if not text and not allow_empty:
            return None
        return truncate_text(text, truncate)

    if fallback is not None:
        fallback_text = _coerce_fallback(fallback)
        if fallback_text is not None:
            return fallback_text

    if fallback_factory is not None:
        try:
            produced = fallback_factory(value)
        except Exception:
            produced = None
        fallback_text = _coerce_fallback(produced)
        if fallback_text is not None:
            return fallback_text

    return None
