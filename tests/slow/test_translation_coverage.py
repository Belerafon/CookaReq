"""Tests for translation coverage."""

import polib
from pathlib import Path
import pytest

pytestmark = pytest.mark.slow


def test_po_files_have_no_missing_translations():
    base = Path('app/locale')
    catalogs = {}
    all_ids = set()
    for lang_dir in base.iterdir():
        po_path = lang_dir / 'LC_MESSAGES' / 'CookaReq.po'
        if po_path.exists():
            catalog = polib.pofile(str(po_path))
            catalogs[lang_dir.name] = catalog
            all_ids.update(entry.msgid for entry in catalog if entry.msgid)
    for lang, catalog in catalogs.items():
        ids = {entry.msgid for entry in catalog if entry.msgid}
        missing = all_ids - ids
        assert not missing, f"{lang} missing translations: {sorted(missing)}"
        empty = [entry.msgid for entry in catalog if entry.msgid and not entry.msgstr]
        assert not empty, f"{lang} has empty translations: {empty}"
