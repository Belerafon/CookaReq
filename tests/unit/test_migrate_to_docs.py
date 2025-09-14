import json
from pathlib import Path

import pytest

from tools.migrate_to_docs import migrate_to_docs

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

    migrate_to_docs(tmp_path, rules="tag:doc=SYS->SYS; tag:doc=HLR->HLR", default="SYS")

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
    assert sys_data["text"] == "First"
    assert sys_data["tags"] == ["alpha"]

    assert hlr_data["id"] == 2
    assert hlr_data["tags"] == ["beta"]

    doc = json.loads((tmp_path / "SYS" / "document.json").read_text(encoding="utf-8"))
    assert doc["prefix"] == "SYS"
    assert doc["digits"] == 3
    assert doc["labels"]["allowFreeform"] is True
