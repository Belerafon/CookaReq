"""JSON serialisation helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from typing import Any

from .strings import coerce_text, describe_unprintable, truncate_text
from .text_inspect import TextUnstableReason, classify_unstable_text


@dataclass(frozen=True)
class JsonSanitizerLimits:
    """Bounds applied while traversing objects for JSON conversion."""

    max_depth: int | None = None
    max_items: int | None = None
    max_string_length: int | None = None


_TRUNCATION_SENTINEL_KEY = "__history_truncated__"


def make_json_safe(
    value: Any,
    *,
    stringify_keys: bool = False,
    sort_sets: bool = True,
    coerce_sequences: bool = False,
    default: Callable[[Any], str] | None = None,
    limits: JsonSanitizerLimits | None = None,
) -> Any:
    """Return a structure compatible with :func:`json.dumps`."""

    if default is None:
        default = repr

    limits = limits or JsonSanitizerLimits()
    enforce_limits = any(
        limit is not None
        for limit in (limits.max_depth, limits.max_items, limits.max_string_length)
    )

    describe_key = partial(describe_unprintable, prefix="unserialisable key")
    describe_value = partial(describe_unprintable, prefix="unserialisable")

    def _apply_string_limit(text: str) -> str:
        if enforce_limits:
            return truncate_text(text, limits.max_string_length)
        return text

    def _depth_exceeded(depth: int) -> bool:
        return (
            enforce_limits
            and limits.max_depth is not None
            and depth >= limits.max_depth
        )

    def _stringify_key(key: Any) -> str:
        if isinstance(key, str):
            return _apply_string_limit(key)
        text = coerce_text(
            key,
            allow_empty=True,
            fallback_factory=describe_key,
            truncate=limits.max_string_length if enforce_limits else None,
        )
        if text:
            reason = classify_unstable_text(text, detect_massive_dumps=False)
            if reason == TextUnstableReason.POINTER_REPR:
                text = None
        if not text:
            text = describe_key(key)
        return text

    def _insert_truncation_marker(
        mapping: dict[Any, Any], *, kind: str, reason: str, omitted: int
    ) -> None:
        key = _TRUNCATION_SENTINEL_KEY
        suffix = 1
        while key in mapping:
            suffix += 1
            key = f"{_TRUNCATION_SENTINEL_KEY}_{suffix}"
        mapping[key] = {
            "kind": kind,
            "reason": reason,
            "omitted": omitted,
        }

    def _append_truncation_marker(
        sequence: list[Any], *, kind: str, reason: str, omitted: int
    ) -> None:
        sequence.append(
            {
                _TRUNCATION_SENTINEL_KEY: {
                    "kind": kind,
                    "reason": reason,
                    "omitted": omitted,
                }
            }
        )

    def _depth_marker(kind: str) -> Any:
        payload = {
            _TRUNCATION_SENTINEL_KEY: {
                "kind": kind,
                "reason": "max_depth",
                "omitted": 0,
            }
        }
        if kind == "sequence":
            return [payload]
        return payload

    def _convert(item: Any, depth: int) -> Any:
        if isinstance(item, Mapping):
            if _depth_exceeded(depth):
                return _depth_marker("mapping")
            if stringify_keys:
                result: dict[str, Any] = {}
                omitted = 0
                for index, (key, val) in enumerate(item.items()):
                    if (
                        enforce_limits
                        and limits.max_items is not None
                        and index >= limits.max_items
                    ):
                        omitted += 1
                        continue
                    result[_stringify_key(key)] = _convert(val, depth + 1)
                if omitted:
                    _insert_truncation_marker(
                        result,
                        kind="mapping",
                        reason="max_items",
                        omitted=omitted,
                    )
                return result
            result_mapping: dict[Any, Any] = {}
            omitted = 0
            for index, (key, val) in enumerate(item.items()):
                if (
                    enforce_limits
                    and limits.max_items is not None
                    and index >= limits.max_items
                ):
                    omitted += 1
                    continue
                result_mapping[key] = _convert(val, depth + 1)
            if omitted:
                _insert_truncation_marker(
                    result_mapping,
                    kind="mapping",
                    reason="max_items",
                    omitted=omitted,
                )
            return result_mapping
        if isinstance(item, list):
            if _depth_exceeded(depth):
                return _depth_marker("sequence")
            converted: list[Any] = []
            omitted = 0
            for index, value in enumerate(item):
                if (
                    enforce_limits
                    and limits.max_items is not None
                    and index >= limits.max_items
                ):
                    omitted += 1
                    continue
                converted.append(_convert(value, depth + 1))
            if omitted:
                _append_truncation_marker(
                    converted,
                    kind="sequence",
                    reason="max_items",
                    omitted=omitted,
                )
            return converted
        if isinstance(item, tuple):
            return _convert(list(item), depth)
        if isinstance(item, set):
            if _depth_exceeded(depth):
                return _depth_marker("sequence")
            converted = [_convert(value, depth + 1) for value in item]
            if sort_sets:
                converted.sort()
            return converted
        if coerce_sequences and isinstance(item, Sequence) and not isinstance(
            item, (str, bytes, bytearray)
        ):
            if _depth_exceeded(depth):
                return _depth_marker("sequence")
            converted: list[Any] = []
            omitted = 0
            for index, value in enumerate(item):
                if (
                    enforce_limits
                    and limits.max_items is not None
                    and index >= limits.max_items
                ):
                    omitted += 1
                    continue
                converted.append(_convert(value, depth + 1))
            if omitted:
                _append_truncation_marker(
                    converted,
                    kind="sequence",
                    reason="max_items",
                    omitted=omitted,
                )
            return converted
        if isinstance(item, str):
            return _apply_string_limit(item)
        if isinstance(item, (int, float, bool)) or item is None:
            return item

        missing = object()
        try:
            converted = default(item)
        except Exception:
            converted = missing
        if converted is item:
            converted = missing

        if converted is not missing:
            if isinstance(converted, Mapping):
                return _convert(converted, depth + 1)
            if isinstance(converted, list):
                return _convert(converted, depth + 1)
            if isinstance(converted, tuple):
                return _convert(list(converted), depth)
            if isinstance(converted, set):
                converted_list = [_convert(value, depth + 1) for value in converted]
                if sort_sets:
                    converted_list.sort()
                return converted_list
            if coerce_sequences and isinstance(converted, Sequence) and not isinstance(
                converted, (str, bytes, bytearray)
            ):
                return _convert(list(converted), depth)
            if isinstance(converted, (str, int, float, bool)) or converted is None:
                return converted

        text = coerce_text(
            item,
            allow_empty=True,
            fallback_factory=describe_value,
            truncate=limits.max_string_length if enforce_limits else None,
        )
        if text:
            reason = classify_unstable_text(text, detect_massive_dumps=False)
            if reason == TextUnstableReason.POINTER_REPR:
                text = None
        if text is not None:
            return _apply_string_limit(text)
        return describe_value(item)

    return _convert(value, 0)


__all__ = ["JsonSanitizerLimits", "make_json_safe"]
