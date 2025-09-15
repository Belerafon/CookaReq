import json
from pathlib import Path

import pytest

from tools.migrate_to_docs import migrate_to_docs, parse_rules

pytestmark = pytest.mark.unit


def write_req(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def test_migrate_to_docs_basic(tmp_path: Path):
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

    migrate_to_docs(tmp_path, rules="label:doc=SYS->SYS; label:doc=HLR->HLR", default="SYS")

    # original files removed
    assert not (tmp_path / "CR-001.json").exists()

    sys_item = tmp_path / "SYS" / "items" / "SYS001.json"
    hlr_item = tmp_path / "HLR" / "items" / "HLR002.json"
    assert sys_item.is_file()
    assert hlr_item.is_file()

    sys_data = json.loads(sys_item.read_text(encoding="utf-8"))
    hlr_data = json.loads(hlr_item.read_text(encoding="utf-8"))

    assert sys_data["id"] == 1
    assert sys_data["title"] == "One"
    assert sys_data["statement"] == "First"
    assert sys_data["labels"] == ["alpha"]

    assert hlr_data["id"] == 2
    assert hlr_data["labels"] == ["beta"]

    doc = json.loads((tmp_path / "SYS" / "document.json").read_text(encoding="utf-8"))
    assert doc["prefix"] == "SYS"
    assert doc["digits"] == 3
    assert doc["labels"]["allowFreeform"] is True


def test_migrate_to_docs_links(tmp_path: Path):
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
        (tmp_path / "SYS" / "items" / "SYS002.json").read_text(encoding="utf-8")
    )
    assert data["links"] == ["SYS001", "EXT-9"]


@pytest.mark.parametrize("legacy_id", [1, "1"])
def test_migrate_to_docs_numeric_ids(tmp_path: Path, legacy_id):
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
    expected_numeric_rid = f"SYS{int(str(legacy_id)):0{digits}d}"

    numeric_path = tmp_path / "SYS" / "items" / f"{expected_numeric_rid}.json"
    assert numeric_path.exists()
    numeric_data = json.loads(numeric_path.read_text(encoding="utf-8"))
    assert numeric_data["id"] == 1
    assert numeric_data["title"] == "Legacy numeric"
    assert numeric_data["labels"] == []
    assert numeric_data.get("links") is None

    consumer_items = list((tmp_path / "SYS" / "items").glob("*.json"))
    consumer_data = None
    for item_path in consumer_items:
        if item_path.name == f"{expected_numeric_rid}.json":
            continue
        data = json.loads(item_path.read_text(encoding="utf-8"))
        if data["title"] == "Consumer":
            consumer_data = data
            break
    assert consumer_data is not None
    assert consumer_data["id"] == 2
    assert consumer_data["labels"] == []
    assert consumer_data["links"] == [expected_numeric_rid, "EXT-9"]


def test_parse_rules_reject_tag_prefix():
    with pytest.raises(ValueError):
        parse_rules("tag:doc=SYS->SYS")
