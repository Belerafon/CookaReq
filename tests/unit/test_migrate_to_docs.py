import json
from dataclasses import fields as dataclass_fields
from pathlib import Path

import pytest

from app.core.model import Requirement
from tools.migrate_to_docs import migrate_to_docs, parse_rules

pytestmark = pytest.mark.unit

REQUIREMENT_KEYS = {
    f.name for f in dataclass_fields(Requirement) if f.name not in {"doc_prefix", "rid"}
}


def write_req(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def test_migrate_to_docs_basic(tmp_path: Path) -> None:
    r1 = {
        "id": "CR-001",
        "title": "One",
        "statement": "First",
        "labels": ["doc=SYS", "alpha"],
        "revision": 1,
    }
    r2 = {
        "id": "CR-002",
        "title": "Two",
        "statement": "Second",
        "labels": ["doc=HLR", "beta"],
    }
    write_req(tmp_path / "CR-001.json", r1)
    write_req(tmp_path / "CR-002.json", r2)

    migrate_to_docs(
        tmp_path,
        rules="label:doc=SYS->SYS; label:doc=HLR->HLR",
        default="SYS",
    )

    # original files removed
    assert not (tmp_path / "CR-001.json").exists()

    sys_item = tmp_path / "SYS" / "items" / "001.json"
    hlr_item = tmp_path / "HLR" / "items" / "002.json"
    assert sys_item.is_file()
    assert hlr_item.is_file()
    sys_names = [p.stem for p in (tmp_path / "SYS" / "items").glob("*.json")]
    hlr_names = [p.stem for p in (tmp_path / "HLR" / "items").glob("*.json")]
    assert all(name.isdigit() for name in sys_names)
    assert all(name.isdigit() for name in hlr_names)

    sys_data = json.loads(sys_item.read_text(encoding="utf-8"))
    hlr_data = json.loads(hlr_item.read_text(encoding="utf-8"))

    assert set(sys_data) == REQUIREMENT_KEYS
    assert sys_data["id"] == 1
    assert sys_data["title"] == "One"
    assert sys_data["statement"] == "First"
    assert sys_data["labels"] == ["alpha"]
    assert sys_data["links"] == []
    assert sys_data["type"] == "requirement"
    assert sys_data["status"] == "draft"
    assert sys_data["owner"] == ""
    assert sys_data["priority"] == "medium"
    assert sys_data["source"] == ""
    assert sys_data["verification"] == "analysis"
    assert sys_data["attachments"] == []

    assert set(hlr_data) == REQUIREMENT_KEYS
    assert hlr_data["id"] == 2
    assert hlr_data["labels"] == ["beta"]
    assert hlr_data["status"] == "draft"

    doc = json.loads((tmp_path / "SYS" / "document.json").read_text(encoding="utf-8"))
    assert "prefix" not in doc
    assert doc["digits"] == 3
    assert doc["labels"]["allowFreeform"] is True
    assert doc["attributes"] == {}


def test_migrate_to_docs_creates_default_document(tmp_path: Path) -> None:
    lone = {
        "id": "HLR-001",
        "title": "Lone HLR",
        "statement": "Only high-level requirement",
        "labels": ["doc=HLR"],
    }

    write_req(tmp_path / "HLR-001.json", lone)

    migrate_to_docs(tmp_path, rules="label:doc=HLR->HLR", default="SYS")

    sys_doc_path = tmp_path / "SYS" / "document.json"
    assert sys_doc_path.exists()
    sys_doc = json.loads(sys_doc_path.read_text(encoding="utf-8"))
    assert "prefix" not in sys_doc
    assert sys_doc["title"] == "SYS"
    assert sys_doc["digits"] == 3
    assert sys_doc["attributes"] == {}

    sys_items_dir = tmp_path / "SYS" / "items"
    assert sys_items_dir.is_dir()
    assert not any(sys_items_dir.iterdir())


def test_migrate_to_docs_links(tmp_path: Path) -> None:
    r1 = {
        "id": "CR-001",
        "title": "One",
        "statement": "First",
        "labels": ["doc=SYS"],
    }
    r2 = {
        "id": "CR-002",
        "title": "Two",
        "statement": "Second",
        "labels": ["doc=SYS"],
        "links": ["CR-001", "EXT-9"],
    }
    write_req(tmp_path / "CR-001.json", r1)
    write_req(tmp_path / "CR-002.json", r2)

    migrate_to_docs(tmp_path, rules="label:doc=SYS->SYS", default="SYS")

    data = json.loads(
        (tmp_path / "SYS" / "items" / "002.json").read_text(encoding="utf-8")
    )
    links = data.get("links", [])
    assert [entry["rid"] for entry in links] == ["SYS001", "EXT-9"]
    assert links[0].get("fingerprint")
    assert links[0].get("suspect") is False
    assert links[1].get("suspect") is True


@pytest.mark.parametrize("legacy_id", [1, "1"])
def test_migrate_to_docs_numeric_ids(tmp_path: Path, legacy_id) -> None:
    numeric = {
        "id": legacy_id,
        "title": "Legacy numeric",
        "statement": "Numeric statement",
        "labels": ["doc=SYS"],
    }
    consumer_links = [legacy_id, "EXT-9"]
    consumer = {
        "id": "CR-002",
        "title": "Consumer",
        "statement": "Reference numeric",
        "labels": ["doc=SYS"],
        "links": consumer_links,
    }

    write_req(tmp_path / "numeric.json", numeric)
    write_req(tmp_path / "consumer.json", consumer)

    migrate_to_docs(tmp_path, rules="label:doc=SYS->SYS", default="SYS")

    doc = json.loads((tmp_path / "SYS" / "document.json").read_text(encoding="utf-8"))
    digits = doc["digits"]
    numeric_id = f"{int(str(legacy_id)):0{digits}d}"
    expected_numeric_rid = f"SYS{numeric_id}"

    numeric_path = tmp_path / "SYS" / "items" / f"{numeric_id}.json"
    assert numeric_path.exists()
    numeric_data = json.loads(numeric_path.read_text(encoding="utf-8"))
    assert numeric_data["id"] == 1
    assert numeric_data["title"] == "Legacy numeric"
    assert numeric_data["labels"] == []
    assert numeric_data["links"] == []

    consumer_items = list((tmp_path / "SYS" / "items").glob("*.json"))
    consumer_data = None
    for item_path in consumer_items:
        if item_path.name == f"{numeric_id}.json":
            continue
        data = json.loads(item_path.read_text(encoding="utf-8"))
        if data["title"] == "Consumer":
            consumer_data = data
            break
    assert consumer_data is not None
    assert consumer_data["id"] == 2
    assert consumer_data["labels"] == []
    links = consumer_data.get("links", [])
    assert [entry["rid"] for entry in links] == [expected_numeric_rid, "EXT-9"]
    assert links[0].get("fingerprint")
    assert links[0].get("suspect") is False


def test_migrate_to_docs_preserves_metadata(tmp_path: Path) -> None:
    legacy = {
        "id": "CR-010",
        "title": "Legacy",
        "statement": "Detailed statement",
        "labels": ["doc=SYS"],
        "status": "approved",
        "owner": "Lead",
        "priority": "high",
        "source": "spec",
        "verification": "test",
        "acceptance": "All tests pass",
        "notes": "Migrated",
        "revision": 3,
    }
    write_req(tmp_path / "legacy.json", legacy)

    migrate_to_docs(tmp_path, rules="label:doc=SYS->SYS", default="SYS")

    item_path = tmp_path / "SYS" / "items" / "010.json"
    data = json.loads(item_path.read_text(encoding="utf-8"))
    assert data["status"] == "approved"
    assert data["owner"] == "Lead"
    assert data["priority"] == "high"
    assert data["source"] == "spec"
    assert data["verification"] == "test"
    assert data["acceptance"] == "All tests pass"
    assert data["notes"] == "Migrated"
    assert data["revision"] == 3


def test_migrate_to_docs_structured_source(tmp_path: Path) -> None:
    structured = {
        "id": "CR-020",
        "title": "Structured source",
        "statement": "Has composite source",
        "labels": ["doc=SYS"],
        "source": {"text": "Spec", "ref": "DOC-9"},
    }
    write_req(tmp_path / "structured.json", structured)

    migrate_to_docs(tmp_path, rules="label:doc=SYS->SYS", default="SYS")

    item_path = tmp_path / "SYS" / "items" / "020.json"
    data = json.loads(item_path.read_text(encoding="utf-8"))
    assert data["source"] == json.dumps(structured["source"], ensure_ascii=False, sort_keys=True)


def test_parse_rules_reject_tag_prefix() -> None:
    with pytest.raises(ValueError):
        parse_rules("tag:doc=SYS->SYS")
