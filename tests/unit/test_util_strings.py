from __future__ import annotations

from app.util.strings import coerce_text


def test_coerce_text_prefers_str() -> None:
    class Custom:
        def __str__(self) -> str:
            return "value"

    assert coerce_text(Custom()) == "value"


def test_coerce_text_falls_back_to_repr() -> None:
    class Custom:
        def __str__(self) -> str:  # pragma: no cover - exercised indirectly
            raise RuntimeError("boom")

        def __repr__(self) -> str:
            return "representation"

    assert coerce_text(Custom()) == "representation"


def test_coerce_text_uses_fallback_when_all_converters_fail() -> None:
    class Custom:
        def __str__(self) -> str:  # pragma: no cover - exercised indirectly
            raise RuntimeError("boom")

        def __repr__(self) -> str:  # pragma: no cover - exercised indirectly
            raise RuntimeError("boom")

    assert coerce_text(Custom(), fallback="fallback") == "fallback"
    assert coerce_text(Custom()) is None
