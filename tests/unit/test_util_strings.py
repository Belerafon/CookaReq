from __future__ import annotations

from app.util.strings import coerce_text, describe_unprintable


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


def test_coerce_text_accepts_fallback_factory() -> None:
    sentinel = object()

    assert (
        coerce_text(
            sentinel,
            converters=(),
            fallback_factory=lambda value: describe_unprintable(
                value, prefix="placeholder"
            ),
        )
        == "<placeholder object>"
    )


def test_coerce_text_decodes_bytes() -> None:
    assert coerce_text(b"value") == "value"


def test_coerce_text_truncates_output_when_requested() -> None:
    assert coerce_text("abcdef", truncate=4) == "abc…"
    assert coerce_text("abcdef", truncate=1) == "…"


def test_describe_unprintable_includes_module_information() -> None:
    class Custom:
        pass

    description = describe_unprintable(Custom(), prefix="sample")
    assert description.startswith("<sample ")
    assert "Custom" in description
