"""Helpers for rendering requirement exports as plain text cards."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .markdown_utils import render_markdown_plain_text

__all__ = ["render_requirement_cards_txt"]


def _normalize_text(value: str) -> list[str]:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.split("\n") if normalized else [""]


def _format_card_field(
    label: str,
    value: str,
    *,
    indent: str = "  ",
    strip_markdown_text: bool = False,
) -> str:
    if strip_markdown_text:
        value = render_markdown_plain_text(value)
    lines = _normalize_text(value)
    if not lines:
        return f"{label}:"
    parts = [f"{label}: {lines[0]}"]
    for line in lines[1:]:
        parts.append(f"{indent}{line}")
    return "\n".join(parts)


def render_requirement_cards_txt(
    headers: Sequence[str],
    rows: Iterable[Sequence[str]],
    *,
    empty_field_placeholder: str | None = None,
    strip_markdown_text: bool = False,
) -> str:
    """Render requirements as a plain text card list."""
    cards: list[str] = []
    for row in rows:
        fields = []
        for header, cell in zip(headers, row, strict=False):
            label = str(header)
            value = "" if cell is None else str(cell)
            if not value:
                if empty_field_placeholder is None:
                    continue
                value = empty_field_placeholder
            fields.append(
                _format_card_field(label, value, strip_markdown_text=strip_markdown_text)
            )
        cards.append("\n".join(fields))
    return "\n\n".join(cards) + "\n"
