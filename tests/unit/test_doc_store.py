import json
from pathlib import Path

import pytest

from app.core.doc_store import (
    Document,
    next_item_id,
    parse_rid,
    load_document,
    load_item,
    list_item_ids,
    rid_for,
    save_document,
    save_item,
)

pytestmark = pytest.mark.unit


def test_document_store_roundtrip(tmp_path: Path):
    doc_dir = tmp_path / "SYS"
    doc = Document(prefix="SYS", title="System", digits=3)
    save_document(doc_dir, doc)

    loaded = load_document(doc_dir)
    assert loaded.prefix == "SYS"
    assert loaded.digits == 3

    item1 = {"id": 1, "title": "One", "text": "First"}
    item2 = {"id": 2, "title": "Two", "text": "Second"}
    save_item(doc_dir, doc, item1)
    save_item(doc_dir, doc, item2)

    assert rid_for(doc, 2) == "SYS002"
    assert (doc_dir / "items" / "SYS002.json").is_file()

    ids = list_item_ids(doc_dir, doc)
    assert ids == {1, 2}

    data, _ = load_item(doc_dir, doc, 2)
    assert data["title"] == "Two"
    assert data["text"] == "Second"


def test_parse_rid_and_next_id(tmp_path: Path):
    doc_dir = tmp_path / "HLR"
    doc = Document(prefix="HLR", title="High", digits=2)
    save_document(doc_dir, doc)

    assert parse_rid("HLR01") == ("HLR", 1)
    assert next_item_id(doc_dir, doc) == 1

    save_item(doc_dir, doc, {"id": 1, "title": "T", "text": "X"})
    assert next_item_id(doc_dir, doc) == 2
