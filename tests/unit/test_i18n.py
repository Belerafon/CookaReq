"""Tests for gettext integration helpers."""

from __future__ import annotations

import os
from pathlib import Path

import polib
import pytest

from app import i18n

pytestmark = pytest.mark.unit


def _make_catalog(base: Path, language: str) -> Path:
    directory = base / language / "LC_MESSAGES"
    directory.mkdir(parents=True)
    po_path = directory / "app.po"
    catalog = polib.POFile()
    catalog.metadata = {
        "Content-Type": "text/plain; charset=UTF-8",
        "Language": language,
        "Plural-Forms": "nplurals=2; plural=(n != 1);",
    }
    catalog.append(polib.POEntry(msgid="hello", msgstr="bonjour"))
    catalog.append(
        polib.POEntry(
            msgid="apple",
            msgid_plural="apples",
            msgstr_plural={0: "pomme", 1: "pommes"},
        )
    )
    catalog.append(
        polib.POEntry(msgctxt="menu", msgid="File", msgstr="Fichier"),
    )
    catalog.append(
        polib.POEntry(msgctxt="button", msgid="File", msgstr="Déposer"),
    )
    catalog.save(po_path)
    return po_path


def test_install_falls_back_to_po_catalog(tmp_path: Path) -> None:
    _make_catalog(tmp_path, "fr")
    i18n.install("app", tmp_path, ["fr"])
    assert i18n.gettext("hello") == "bonjour"


def test_install_detects_language_from_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(os.environ, "LANGUAGE", "fr")
    _make_catalog(tmp_path, "fr")
    i18n.install("app", tmp_path)
    assert i18n.gettext("hello") == "bonjour"


def test_translate_resource_combines_fragments(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_gettext(message: str) -> str:
        captured["message"] = message
        return f"translated:{message}"

    monkeypatch.setattr(i18n, "gettext", fake_gettext, raising=False)
    result = i18n.translate_resource(["first", "second"])
    assert captured["message"] == "first second"
    assert result == "translated:first second"


def test_plural_and_context_translations(tmp_path: Path) -> None:
    _make_catalog(tmp_path, "fr")
    i18n.install("app", tmp_path, ["fr"])
    assert i18n.ngettext("apple", "apples", 1) == "pomme"
    assert i18n.ngettext("apple", "apples", 3) == "pommes"
    assert i18n.pgettext("menu", "File") == "Fichier"
    assert i18n.pgettext("button", "File") == "Déposer"
