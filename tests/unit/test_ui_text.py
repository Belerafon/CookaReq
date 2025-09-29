from app.ui.text import normalize_for_display


def test_normalize_for_display_hyphen_between_letters() -> None:
    source = "single\u2010folder"
    assert normalize_for_display(source) == "single-folder"


def test_normalize_for_display_non_breaking_hyphen() -> None:
    source = "test\u2011sample"
    assert normalize_for_display(source) == "test-sample"


def test_normalize_for_display_soft_hyphen() -> None:
    source = "work\u00adflow"
    assert normalize_for_display(source) == "work-flow"


def test_normalize_for_display_preserves_en_dash() -> None:
    text = "value – range"
    assert normalize_for_display(text) == text
