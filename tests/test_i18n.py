from app import i18n


def test_parse_po_multiline_and_unfinished(tmp_path):
    po_content = (
        "# comment\n"
        "msgid \"hello\"\n"
        "msgstr \"\"\n\n"
        "msgid \"multi\"\n"
        "\"id\"\n"
        "msgstr \"multi\"\n"
        "\"str\"\n\n"
        "msgid \"unfinished\"\n"
        "# TODO\n"
    )
    po_path = tmp_path / "sample.po"
    po_path.write_text(po_content, encoding="utf-8")
    data = i18n._parse_po(po_path)
    assert data == {"hello": "", "multiid": "multistr"}


def test_install_selects_locale_and_falls_back(tmp_path, monkeypatch):
    fr_dir = tmp_path / "fr" / "LC_MESSAGES"
    fr_dir.mkdir(parents=True)
    (fr_dir / "app.po").write_text(
        'msgid "hello"\nmsgstr "bonjour"\n', encoding="utf-8"
    )

    monkeypatch.setattr(i18n, "_translations", {})
    monkeypatch.setattr(i18n, "_missing", set())

    i18n.install("app", str(tmp_path), languages=["de", "fr"])
    assert i18n.gettext("hello") == "bonjour"

    i18n.install("app", str(tmp_path), languages=["es"])
    assert i18n._translations == {}
    assert i18n.gettext("hello") == "hello"
