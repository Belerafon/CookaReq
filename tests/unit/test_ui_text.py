from app.ui.text import normalize_for_display


def test_normalize_for_display_hyphen_between_letters() -> None:
    source = "одно\u2010папочный"
    assert normalize_for_display(source) == "одно-папочный"


def test_normalize_for_display_non_breaking_hyphen() -> None:
    source = "тест\u2011пример"
    assert normalize_for_display(source) == "тест-пример"


def test_normalize_for_display_soft_hyphen() -> None:
    source = "мас\u00adштаб"
    assert normalize_for_display(source) == "мас-штаб"


def test_normalize_for_display_preserves_en_dash() -> None:
    text = "значение – диапазон"
    assert normalize_for_display(text) == text
