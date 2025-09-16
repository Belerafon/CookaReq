"""Minimal gettext-like translations using .po files.

This module loads translations from plain text ``.po`` files at runtime,
avoiding the need for compiled ``.mo`` binaries.  It provides a small subset
of the ``gettext`` API: ``gettext`` (aliased as ``_``) and ``install`` to set
the active language.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable
from pathlib import Path


def _unescape(text: str) -> str:
    """Unescape common sequences in PO file strings."""
    return (
        text.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )


def _escape(text: str) -> str:
    """Escape strings for writing to PO files."""
    return (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


_translations: dict[str, str] = {}
_missing: set[str] = set()
_lock = threading.Lock()


def gettext(message: str) -> str:
    """Return translated ``message`` or the original if not found.

    Untranslated messages are collected for later persistence in
    ``missing.po`` so they can be added to the main catalog.
    """
    translated = _translations.get(message)
    if translated is None:
        with _lock:
            _missing.add(message)
        return message
    return translated


_ = gettext  # public alias used by UI modules


def translate_resource(message: str | Iterable[str]) -> str:
    """Translate text loaded from external resources.

    ``message`` may be a single string or an iterable of string fragments.  In
    the latter case the fragments are joined with a single space before being
    translated so that PO files see the complete sentence.
    """

    if isinstance(message, str):
        combined = message
    else:
        combined = " ".join(str(part) for part in message)
    return gettext(combined)


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
                msgid = _unescape(line[6:].strip().strip('"'))
                msgstr = None
                state = "msgid"
                continue
            if line.startswith("msgstr "):
                msgstr = _unescape(line[7:].strip().strip('"'))
                state = "msgstr"
                continue
            if line.startswith('"') and state == "msgid":
                msgid += _unescape(line.strip('"'))
                continue
            if line.startswith('"') and state == "msgstr":
                msgstr += _unescape(line.strip('"'))
                continue
    if msgid not in (None, "") and msgstr is not None:
        result[msgid] = msgstr
    return result


def flush_missing(path: Path) -> None:
    """Atomically write collected missing ``msgid`` values to ``path``.

    The file is written in ``.po`` format with empty ``msgstr`` fields.  Only
    new ``msgid`` values are appended; existing entries are preserved.
    ``path`` is created along with its parent directories if needed.
    """
    with _lock:
        if not _missing:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: set[str] = set()
        if path.exists():
            existing = set(_parse_po(path))
            with path.open(encoding="utf-8") as f:
                lines = f.readlines()
        else:
            lines = []
        new = [m for m in sorted(_missing) if m not in existing]
        if not new:
            _missing.clear()
            return
        for msg in new:
            lines.append(f'msgid "{_escape(msg)}"\n')
            lines.append('msgstr ""\n\n')
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            f.writelines(lines)
        tmp_path.replace(path)
        _missing.clear()


def install(
    domain: str,
    localedir: str,
    languages: Iterable[str] | None = None,
) -> None:
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
