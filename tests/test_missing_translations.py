"""Tests for missing translations."""

import threading
from app import i18n


def test_flush_missing_writes_unique_msgids(tmp_path):
    """Missing msgids are collected once and flushed to file atomically."""
    i18n._translations = {}
    i18n._missing.clear()

    def worker():
        for _ in range(5):
            i18n.gettext("untranslated")

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    path = tmp_path / "missing.po"
    i18n.flush_missing(path)
    data = path.read_text(encoding="utf-8")
    assert data.count('msgid "untranslated"') == 1

    i18n.gettext("untranslated")
    i18n.gettext("second")
    i18n.flush_missing(path)
    data = path.read_text(encoding="utf-8")
    assert data.count('msgid "untranslated"') == 1
    assert 'msgid "second"' in data
