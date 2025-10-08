"""High-level helpers for runtime gettext translations."""

from __future__ import annotations

import gettext as _gettext
import os
from collections.abc import Iterable, Sequence
from io import BytesIO
from pathlib import Path
from typing import Final

import polib
from gettext import GNUTranslations, NullTranslations, _expand_lang

__all__ = [
    "_",
    "gettext",
    "ngettext",
    "pgettext",
    "npgettext",
    "install",
    "translate_resource",
    "get_translation",
]

_TRANSLATION: NullTranslations = NullTranslations()


def get_translation() -> NullTranslations:
    """Return the currently active translation object."""
    return _TRANSLATION


def gettext(message: str) -> str:
    """Translate *message* using the active gettext catalogue."""
    return _TRANSLATION.gettext(message)


def ngettext(singular: str, plural: str, number: int) -> str:
    """Translate pluralisable message based on *number*."""
    return _TRANSLATION.ngettext(singular, plural, number)


def pgettext(context: str, message: str) -> str:
    """Translate *message* for the supplied *context*."""
    return _TRANSLATION.pgettext(context, message)


def npgettext(context: str, singular: str, plural: str, number: int) -> str:
    """Translate pluralisable message tied to *context*."""
    return _TRANSLATION.npgettext(context, singular, plural, number)


_: Final = gettext


def translate_resource(message: str | Iterable[str]) -> str:
    """Translate text loaded from bundled resources.

    ``message`` may be a string or an iterable of fragments. In the latter case
    the fragments are joined with a single space before translation so that the
    catalogue sees the full sentence.
    """
    if isinstance(message, str):
        combined = message
    else:
        combined = " ".join(str(part) for part in message)
    return gettext(combined)


def install(
    domain: str,
    localedir: str | os.PathLike[str],
    languages: Iterable[str] | None = None,
) -> NullTranslations:
    """Load translations for *domain* and make them globally available."""
    localedir_path = Path(localedir)
    requested = _prepare_language_list(languages)
    translation = _gettext.translation(
        domain,
        localedir=str(localedir_path),
        languages=requested or None,
        fallback=True,
    )
    if isinstance(translation, NullTranslations):
        fallback = _load_po_translation(domain, localedir_path, requested)
        if fallback is not None:
            translation = fallback
    _set_translation(translation)
    translation.install(names=("gettext", "ngettext", "pgettext", "npgettext"))
    return translation


def _set_translation(translation: NullTranslations) -> None:
    global _TRANSLATION
    _TRANSLATION = translation


def _prepare_language_list(languages: Iterable[str] | None) -> list[str]:
    if languages is None:
        return _languages_from_environment()
    return _expand_languages(languages)


def _languages_from_environment() -> list[str]:
    raw: list[str] = []
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name)
        if not value:
            continue
        raw.extend(token.strip() for token in value.split(":") if token.strip())
    return _expand_languages(raw)


def _expand_languages(languages: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    expanded: list[str] = []
    for language in languages:
        if not language:
            continue
        for candidate in _expand_lang(language):
            if candidate and candidate not in seen:
                seen.add(candidate)
                expanded.append(candidate)
    return expanded


def _load_po_translation(
    domain: str,
    localedir: Path,
    languages: Sequence[str],
) -> NullTranslations | None:
    for language in languages:
        po_path = localedir / language / "LC_MESSAGES" / f"{domain}.po"
        if not po_path.exists():
            continue
        try:
            catalog = polib.pofile(str(po_path))
        except Exception:  # pragma: no cover - propagates to fallback behaviour
            continue
        mo_data = catalog.to_binary()
        return GNUTranslations(BytesIO(mo_data))
    return None
