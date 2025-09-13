"""Tests for locale."""

import pytest
from app.i18n import _, install

from app.ui import locale
from app.core import model


def test_round_trip():
    install("CookaReq", "app/locale", ["en"])
    for category, mapping in locale.EN_LABELS.items():
        for code, label in mapping.items():
            assert locale.code_to_label(category, code) == label
            assert locale.label_to_code(category, label) == code


def test_unknown_values_return_input():
    assert locale.code_to_label('type', 'unknown') == 'unknown'
    assert locale.label_to_code('type', 'Unknown') == 'Unknown'


def _enum_label(e):
    return e.name.replace('_', ' ').lower().capitalize()


@pytest.mark.parametrize(
    'enum_cls,mapping',
    [
        (model.RequirementType, locale.TYPE),
        (model.Status, locale.STATUS),
        (model.Priority, locale.PRIORITY),
        (model.Verification, locale.VERIFICATION),
    ],
)
def test_localizations_match_enums(enum_cls, mapping):
    install("CookaReq", "app/locale", ["en"])
    expected = {e.value: _(_enum_label(e)) for e in enum_cls}
    assert mapping == expected
