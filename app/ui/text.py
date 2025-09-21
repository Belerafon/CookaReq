"""Helpers for preparing arbitrary Unicode text for wx widgets."""

from __future__ import annotations

import unicodedata

_SOFT_HYPHEN = "\u00ad"
_HYPHEN = "\u2010"
_NON_BREAKING_HYPHEN = "\u2011"
_FIGURE_DASH = "\u2012"
_EN_DASH = "\u2013"
_EM_DASH = "\u2014"
_HORIZONTAL_BAR = "\u2015"
_MINUS_SIGN = "\u2212"

_DIRECT_TRANSLATIONS: dict[str, str] = {
    _EN_DASH: "–",
    _EM_DASH: "—",
    _HORIZONTAL_BAR: "—",
    _MINUS_SIGN: "−",
}


def normalize_for_display(value: str) -> str:
    """Return *value* with punctuation normalised for safer rendering."""

    if not value:
        return value

    result: list[str] = []
    length = len(value)
    for index, char in enumerate(value):
        if char in (_HYPHEN, _NON_BREAKING_HYPHEN, _FIGURE_DASH, _SOFT_HYPHEN):
            previous = value[index - 1] if index else ""
            following = value[index + 1] if index + 1 < length else ""
            result.append(_replace_special_hyphen(char, previous, following))
            continue
        replacement = _DIRECT_TRANSLATIONS.get(char)
        if replacement is not None:
            result.append(replacement)
            continue
        result.append(char)
    return "".join(result)


def _replace_special_hyphen(char: str, previous: str, following: str) -> str:
    if _is_word_char(previous) or _is_word_char(following):
        return "-"
    return "–"


def _is_word_char(char: str) -> bool:
    if not char:
        return False
    category = unicodedata.category(char)
    if not category:
        return False
    if category[0] in {"L", "N"}:
        return True
    return char == "_"

