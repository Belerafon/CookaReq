import json
from pathlib import Path

import pytest

from app.core.document_store import (
    Document,
    delete_document,
    delete_item,
    item_path,
    load_document,
    load_documents,
    load_item,
    list_item_ids,
    next_item_id,
    parse_rid,
    plan_delete_document,
    plan_delete_item,
    rid_for,
    save_document,
    save_item,
)
from app.core.model import requirement_fingerprint

pytestmark = pytest.mark.unit


def test_document_rejects_unexpected_arguments() -> None:
    with pytest.raises(TypeError):
        Document(prefix="SYS", title="System", legacy="value")


def test_document_store_roundtrip(tmp_path: Path):
    doc_dir = tmp_path / "SYS"
    doc = Document(prefix="SYS", title="System")
    save_document(doc_dir, doc)

    loaded = load_document(doc_dir)
    assert loaded.prefix == "SYS"

    item1 = {"id": 1, "title": "One", "statement": "First"}
    item2 = {"id": 2, "title": "Two", "statement": "Second"}
    save_item(doc_dir, doc, item1)
    save_item(doc_dir, doc, item2)

    assert rid_for(doc, 2) == "SYS2"
    assert item_path(doc_dir, doc, 2).is_file()

    ids = list_item_ids(doc_dir, doc)
    assert ids == {1, 2}

    data, _ = load_item(doc_dir, doc, 2)
    assert data["title"] == "Two"
    assert data["statement"] == "Second"


def test_load_document_drops_unknown_fields(tmp_path: Path) -> None:
    doc_dir = tmp_path / "SYS"
    doc_dir.mkdir()
    doc_path = doc_dir / "document.json"
    with doc_path.open("w", encoding="utf-8") as fh:
        json.dump({"title": "System", "legacy": "value"}, fh)

    loaded = load_document(doc_dir)

    assert loaded.title == "System"

    save_document(doc_dir, loaded)

    stored = json.loads(doc_path.read_text(encoding="utf-8"))
    assert stored == {
        "title": "System",
        "parent": None,
        "labels": {"allowFreeform": False, "defs": []},
        "attributes": {},
    }


def test_parse_rid_and_next_id(tmp_path: Path):
    doc_dir = tmp_path / "HLR"
    doc = Document(prefix="HLR", title="High")
    save_document(doc_dir, doc)

    assert parse_rid("HLR1") == ("HLR", 1)
    assert parse_rid("sys5") == ("sys", 5)
    assert next_item_id(doc_dir, doc) == 1

    save_item(doc_dir, doc, {"id": 1, "title": "T", "statement": "X"})
    assert next_item_id(doc_dir, doc) == 2


def test_delete_item_removes_links(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System")
    hlr_doc = Document(prefix="HLR", title="High", parent="SYS")
    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)
    save_item(tmp_path / "SYS", sys_doc, {"id": 1, "title": "S", "statement": ""})
    save_item(
        tmp_path / "HLR",
        hlr_doc,
        {"id": 1, "title": "H", "statement": "", "links": ["SYS1"]},
    )
    docs = load_documents(tmp_path)
    assert delete_item(tmp_path, "SYS1", docs) is True
    # parent file removed
    assert not item_path(tmp_path / "SYS", sys_doc, 1).exists()
    # link cleaned
    data, _ = load_item(tmp_path / "HLR", hlr_doc, 1)
    assert data.get("links") in (None, [])


def test_delete_document_recursively(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System")
    hlr_doc = Document(prefix="HLR", title="High", parent="SYS")
    llr_doc = Document(prefix="LLR", title="Low", parent="HLR")
    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)
    save_document(tmp_path / "LLR", llr_doc)
    save_item(tmp_path / "SYS", sys_doc, {"id": 1, "title": "S", "statement": ""})
    save_item(tmp_path / "HLR", hlr_doc, {"id": 1, "title": "H", "statement": "", "links": ["SYS1"]})
    save_item(tmp_path / "LLR", llr_doc, {"id": 1, "title": "L", "statement": "", "links": ["HLR1"]})
    docs = load_documents(tmp_path)
    assert delete_document(tmp_path, "HLR", docs) is True
    assert not (tmp_path / "HLR").exists()
    assert not (tmp_path / "LLR").exists()
    assert (tmp_path / "SYS").is_dir()


def test_plan_delete_item_lists_references(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System")
    hlr_doc = Document(prefix="HLR", title="High", parent="SYS")
    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)
    save_item(tmp_path / "SYS", sys_doc, {"id": 1, "title": "S", "statement": ""})
    save_item(
        tmp_path / "HLR",
        hlr_doc,
        {"id": 1, "title": "H", "statement": "", "links": ["SYS1"]},
    )
    docs = load_documents(tmp_path)
    exists, refs = plan_delete_item(tmp_path, "SYS1", docs)
    assert exists is True
    assert refs == ["HLR1"]
    # nothing removed
    assert item_path(tmp_path / "SYS", sys_doc, 1).exists()
    data, _ = load_item(tmp_path / "HLR", hlr_doc, 1)
    parent_data, _ = load_item(tmp_path / "SYS", sys_doc, 1)
    expected_fp = requirement_fingerprint(parent_data)
    assert data.get("links") == [{"rid": "SYS1", "fingerprint": expected_fp}]


def test_plan_delete_document_lists_subtree(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System")
    hlr_doc = Document(prefix="HLR", title="High", parent="SYS")
    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)
    save_item(tmp_path / "SYS", sys_doc, {"id": 1, "title": "S", "statement": ""})
    save_item(tmp_path / "HLR", hlr_doc, {"id": 1, "title": "H", "statement": ""})
    docs = load_documents(tmp_path)
    doc_list, item_list = plan_delete_document(tmp_path, "SYS", docs)
    assert set(doc_list) == {"SYS", "HLR"}
    assert set(item_list) == {"SYS1", "HLR1"}
    # filesystem intact
    assert (tmp_path / "SYS").exists()
    assert (tmp_path / "HLR").exists()
