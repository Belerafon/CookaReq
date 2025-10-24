"""Tests for locale."""

import pytest

from app.core import model
from app.i18n import _, install
from app.ui import locale

pytestmark = pytest.mark.unit


def test_round_trip():
    install("CookaReq", "app/locale", ["en"])
    for category, mapping in locale.EN_LABELS.items():
        for code, msgid in mapping.items():
            assert locale.code_to_label(category, code) == _(msgid)
            assert locale.label_to_code(category, msgid) == code


def test_unknown_values_return_input():
    assert locale.code_to_label("type", "unknown") == "unknown"
    assert locale.label_to_code("type", "Unknown") == "Unknown"


def _enum_label(e):
    return e.name.replace("_", " ").lower().capitalize()


@pytest.mark.parametrize(
    ("enum_cls", "category"),
    [
        (model.RequirementType, "type"),
        (model.Status, "status"),
        (model.Priority, "priority"),
        (model.Verification, "verification"),
    ],
)
def test_localizations_match_enums(enum_cls, category):
    install("CookaReq", "app/locale", ["en"])
    expected = {e.value: _enum_label(e) for e in enum_cls}
    assert locale.EN_LABELS[category] == expected


def test_russian_labels_round_trip():
    install("CookaReq", "app/locale", ["ru"])
    assert locale.code_to_label("status", "draft") == "Черновик"
    assert locale.code_to_label("verification", "analysis") == "Анализ"
    assert locale.label_to_code("status", "Черновик") == "draft"
    assert locale.label_to_code("verification", "Анализ") == "analysis"
    install("CookaReq", "app/locale", ["en"])
