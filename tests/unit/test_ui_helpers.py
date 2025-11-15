from __future__ import annotations

from app.ui.helpers import format_error_message


def test_format_error_message_handles_unprintable_mapping() -> None:
    class Broken:
        def __str__(self) -> str:  # pragma: no cover - exercised indirectly
            raise RuntimeError("boom")

    message = {"message": Broken()}

    assert format_error_message(message, fallback="fallback") == "fallback"


def test_format_error_message_handles_unprintable_exception() -> None:
    class BrokenError(Exception):
        def __str__(self) -> str:  # pragma: no cover - exercised indirectly
            raise RuntimeError("boom")

    error = BrokenError()

    assert format_error_message(error, fallback="fallback") == "fallback"


def test_format_error_message_preserves_valid_values() -> None:
    payload = {"code": "E", "message": "details"}

    assert format_error_message(payload) == "E: details"
