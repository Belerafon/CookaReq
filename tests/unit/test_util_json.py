"""Tests for :mod:`app.util.json`."""

from __future__ import annotations

from types import SimpleNamespace

from app.util.json import make_json_safe


def test_make_json_safe_basic_conversion() -> None:
    value = {
        "numbers": {3, 1, 2},
        "tuple": ("a", "b"),
        "custom": SimpleNamespace(name="value"),
    }

    result = make_json_safe(value)

    assert result["numbers"] == [1, 2, 3]
    assert result["tuple"] == ["a", "b"]
    assert isinstance(result["custom"], str)
    assert result["custom"].startswith("namespace(")


def test_make_json_safe_stringifies_keys_when_requested() -> None:
    value = {1: "one", "nested": {2: "two"}}

    result = make_json_safe(value, stringify_keys=True)

    assert set(result.keys()) == {"1", "nested"}
    assert set(result["nested"].keys()) == {"2"}


def test_make_json_safe_allows_unsorted_sets() -> None:
    class CustomSet(set):
        def __init__(self) -> None:
            super().__init__({"first", "second"})
            self._ordered = ["second", "first"]

        def __iter__(self):  # type: ignore[override]
            yield from self._ordered

    custom = CustomSet()

    unsorted_result = make_json_safe(custom, sort_sets=False)
    assert unsorted_result == ["second", "first"]

    sorted_result = make_json_safe(custom, sort_sets=True)
    assert sorted_result == ["first", "second"]


def test_make_json_safe_sequence_control() -> None:
    default_result = make_json_safe(range(3))
    assert default_result == "range(0, 3)"

    coerced_result = make_json_safe(range(3), coerce_sequences=True)
    assert coerced_result == [0, 1, 2]
