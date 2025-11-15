"""JSON serialisation helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from collections.abc import Callable

from .strings import coerce_text


def make_json_safe(
    value: Any,
    *,
    stringify_keys: bool = False,
    sort_sets: bool = True,
    coerce_sequences: bool = False,
    default: Callable[[Any], str] | None = None,
) -> Any:
    """Return a structure compatible with :func:`json.dumps`.

    Parameters
    ----------
    value:
        Arbitrary Python object that should be serialisable.
    stringify_keys:
        Convert mapping keys to strings when ``True``.
    sort_sets:
        When ``True`` the contents of :class:`set` objects are sorted to make
        the output deterministic. When ``False`` the original iteration order
        is preserved.
    coerce_sequences:
        Convert arbitrary :class:`~collections.abc.Sequence` instances into
        lists when ``True``. When ``False`` only lists and tuples are coerced.
    default:
        Fallback callable used for unsupported objects. Defaults to
        :func:`repr` to match :mod:`json` behaviour.
    """
    if default is None:
        default = repr

    def convert(item: Any) -> Any:
        return make_json_safe(
            item,
            stringify_keys=stringify_keys,
            sort_sets=sort_sets,
            coerce_sequences=coerce_sequences,
            default=default,
        )

    if isinstance(value, Mapping):
        if stringify_keys:
            result: dict[str, Any] = {}
            for key, val in value.items():
                if isinstance(key, str):
                    key_text = key
                else:
                    key_text = coerce_text(
                        key,
                        allow_empty=True,
                        fallback=f"<unprintable {type(key).__name__}>",
                    ) or f"<unprintable {type(key).__name__}>"
                result[key_text] = convert(val)
            return result
        return {key: convert(val) for key, val in value.items()}
    if isinstance(value, list):
        return [convert(item) for item in value]
    if isinstance(value, tuple):
        return [convert(item) for item in value]
    if isinstance(value, set):
        converted = [convert(item) for item in value]
        if sort_sets:
            return sorted(converted)
        return converted
    if coerce_sequences and isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [convert(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        converted = default(value)
    except Exception:
        converted = None

    if isinstance(converted, str):
        return converted
    if converted is not None:
        return converted

    return coerce_text(
        value,
        allow_empty=True,
        fallback=f"<unprintable {type(value).__name__}>",
    )


__all__ = ["make_json_safe"]
