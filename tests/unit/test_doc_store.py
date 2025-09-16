from pathlib import Path

import pytest

from app.core.document_store import (
    Document,
    delete_document,
    next_item_id,
    parse_rid,
    load_document,
    load_item,
    list_item_ids,
    rid_for,
    save_document,
    save_item,
    delete_item,
    load_documents,
    plan_delete_document,
    plan_delete_item,
)

pytestmark = pytest.mark.unit


def test_document_store_roundtrip(tmp_path: Path):
    doc_dir = tmp_path / "SYS"
    doc = Document(prefix="SYS", title="System", digits=3)
    save_document(doc_dir, doc)

    loaded = load_document(doc_dir)
    assert loaded.prefix == "SYS"
    assert loaded.digits == 3

    item1 = {"id": 1, "title": "One", "statement": "First"}
    item2 = {"id": 2, "title": "Two", "statement": "Second"}
    save_item(doc_dir, doc, item1)
    save_item(doc_dir, doc, item2)

    assert rid_for(doc, 2) == "SYS002"
    assert (doc_dir / "items" / "SYS002.json").is_file()

    ids = list_item_ids(doc_dir, doc)
    assert ids == {1, 2}

    data, _ = load_item(doc_dir, doc, 2)
    assert data["title"] == "Two"
    assert data["statement"] == "Second"


def test_parse_rid_and_next_id(tmp_path: Path):
    doc_dir = tmp_path / "HLR"
    doc = Document(prefix="HLR", title="High", digits=2)
    save_document(doc_dir, doc)

    assert parse_rid("HLR01") == ("HLR", 1)
    assert next_item_id(doc_dir, doc) == 1

    save_item(doc_dir, doc, {"id": 1, "title": "T", "statement": "X"})
    assert next_item_id(doc_dir, doc) == 2


def test_delete_item_removes_links(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System", digits=3)
    hlr_doc = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)
    save_item(tmp_path / "SYS", sys_doc, {"id": 1, "title": "S", "statement": ""})
    save_item(
        tmp_path / "HLR",
        hlr_doc,
        {"id": 1, "title": "H", "statement": "", "links": ["SYS001"]},
    )
    docs = load_documents(tmp_path)
    assert delete_item(tmp_path, "SYS001", docs) is True
    # parent file removed
    assert not (tmp_path / "SYS" / "items" / "SYS001.json").exists()
    # link cleaned
    data, _ = load_item(tmp_path / "HLR", hlr_doc, 1)
    assert data.get("links") == []


def test_delete_document_recursively(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System", digits=3)
    hlr_doc = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    llr_doc = Document(prefix="LLR", title="Low", digits=2, parent="HLR")
    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)
    save_document(tmp_path / "LLR", llr_doc)
    save_item(tmp_path / "SYS", sys_doc, {"id": 1, "title": "S", "statement": ""})
    save_item(tmp_path / "HLR", hlr_doc, {"id": 1, "title": "H", "statement": "", "links": ["SYS001"]})
    save_item(tmp_path / "LLR", llr_doc, {"id": 1, "title": "L", "statement": "", "links": ["HLR01"]})
    docs = load_documents(tmp_path)
    assert delete_document(tmp_path, "HLR", docs) is True
    assert not (tmp_path / "HLR").exists()
    assert not (tmp_path / "LLR").exists()
    assert (tmp_path / "SYS").is_dir()


def test_plan_delete_item_lists_references(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System", digits=3)
    hlr_doc = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)
    save_item(tmp_path / "SYS", sys_doc, {"id": 1, "title": "S", "statement": ""})
    save_item(
        tmp_path / "HLR",
        hlr_doc,
        {"id": 1, "title": "H", "statement": "", "links": ["SYS001"]},
    )
    docs = load_documents(tmp_path)
    exists, refs = plan_delete_item(tmp_path, "SYS001", docs)
    assert exists is True
    assert refs == ["HLR01"]
    # nothing removed
    assert (tmp_path / "SYS" / "items" / "SYS001.json").exists()
    data, _ = load_item(tmp_path / "HLR", hlr_doc, 1)
    assert data.get("links") == ["SYS001"]


def test_plan_delete_document_lists_subtree(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System", digits=3)
    hlr_doc = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)
    save_item(tmp_path / "SYS", sys_doc, {"id": 1, "title": "S", "statement": ""})
    save_item(tmp_path / "HLR", hlr_doc, {"id": 1, "title": "H", "statement": ""})
    docs = load_documents(tmp_path)
    doc_list, item_list = plan_delete_document(tmp_path, "SYS", docs)
    assert set(doc_list) == {"SYS", "HLR"}
    assert set(item_list) == {"SYS001", "HLR01"}
    # filesystem intact
    assert (tmp_path / "SYS").exists()
    assert (tmp_path / "HLR").exists()
