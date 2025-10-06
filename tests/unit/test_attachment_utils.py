"""Tests for attachment heuristics."""

from app.ui.agent_chat_panel.attachment_utils import looks_like_plain_text


def test_plain_text_is_accepted():
    assert looks_like_plain_text("Hello, world!\nThis is a note.")


def test_binary_null_byte_is_rejected():
    assert not looks_like_plain_text("abc\x00def")


def test_many_control_characters_are_rejected():
    noisy = "a" * 50 + "\x02" * 10 + "b" * 50
    assert not looks_like_plain_text(noisy)


def test_escape_sequences_allowed():
    assert looks_like_plain_text("\x1b[31mКрасный текст\x1b[0m")
