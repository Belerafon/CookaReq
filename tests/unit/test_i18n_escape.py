"""Tests for i18n escape."""

import pytest

from app import i18n

pytestmark = pytest.mark.unit

def test_parse_po_unescape(tmp_path):
    po = tmp_path / "sample.po"
    po.write_text('msgid "Line\\nBreak\\tTab"\nmsgstr "Перевод\\nСтрока\\tТаб"\n', encoding="utf-8")
    data = i18n._parse_po(po)
    assert data["Line\nBreak\tTab"] == "Перевод\nСтрока\tТаб"

def test_flush_missing_escape(tmp_path):
    i18n._missing.clear()
    i18n._missing.add("Line\nBreak\tTab")
    path = tmp_path / "missing.po"
    i18n.flush_missing(path)
    content = path.read_text(encoding="utf-8")
    assert "Line\\nBreak\\tTab" in content
    parsed = i18n._parse_po(path)
    assert "Line\nBreak\tTab" in parsed
    i18n._missing.clear()
