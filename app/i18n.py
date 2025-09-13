"""Minimal gettext-like translations using .po files.

This module loads translations from plain text ``.po`` files at runtime,
avoiding the need for compiled ``.mo`` binaries.  It provides a small subset
of the ``gettext`` API: ``gettext`` (aliased as ``_``) and ``install`` to set
the active language.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

_translations: dict[str, str] = {}


def gettext(message: str) -> str:
    """Return translated ``message`` or the original if not found."""
    return _translations.get(message, message)


_ = gettext  # public alias used by UI modules


def _parse_po(path: Path) -> dict[str, str]:
    """Parse a very small subset of the PO file format.

    Only ``msgid``/``msgstr`` pairs are supported; comments, plural forms and
    contexts are ignored.  This is sufficient for the project's current
    translation needs.
    """
    result: dict[str, str] = {}
    msgid: str | None = None
    msgstr: str | None = None
    state: str | None = None
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                if msgid not in (None, "") and msgstr is not None:
                    result[msgid] = msgstr
                msgid = msgstr = state = None
                continue
            if line.startswith("msgid "):
                msgid = line[6:].strip().strip('"')
                msgstr = None
                state = "msgid"
                continue
            if line.startswith("msgstr "):
                msgstr = line[7:].strip().strip('"')
                state = "msgstr"
                continue
            if line.startswith('"') and state == "msgid":
                msgid += line.strip('"')
                continue
            if line.startswith('"') and state == "msgstr":
                msgstr += line.strip('"')
                continue
    if msgid not in (None, "") and msgstr is not None:
        result[msgid] = msgstr
    return result


def install(domain: str, localedir: str, languages: Iterable[str] | None = None) -> None:
    """Load translations for ``languages`` and make ``gettext`` use them."""
    global _translations
    languages = list(languages or [])
    for lang in languages:
        po_path = Path(localedir) / lang / "LC_MESSAGES" / f"{domain}.po"
        if po_path.exists():
            _translations = _parse_po(po_path)
            break
    else:
        _translations = {}
