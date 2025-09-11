from app.ui import locale


def test_round_trip():
    for category, mapping in locale.TRANSLATIONS.items():
        for code, ru in mapping.items():
            assert locale.code_to_ru(category, code) == ru
            assert locale.ru_to_code(category, ru) == code


def test_unknown_values_return_input():
    assert locale.code_to_ru('type', 'unknown') == 'unknown'
    assert locale.ru_to_code('type', 'Неизвестно') == 'Неизвестно'
