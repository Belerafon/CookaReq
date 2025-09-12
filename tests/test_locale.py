from app.ui import locale


def test_round_trip():
    for category, mapping in locale.EN_LABELS.items():
        for code, label in mapping.items():
            assert locale.code_to_label(category, code) == label
            assert locale.label_to_code(category, label) == code


def test_unknown_values_return_input():
    assert locale.code_to_label('type', 'unknown') == 'unknown'
    assert locale.label_to_code('type', 'Unknown') == 'Unknown'
