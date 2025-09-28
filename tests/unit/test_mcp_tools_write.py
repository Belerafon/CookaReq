import json
from pathlib import Path

from app.core.document_store import (
    Document,
    DocumentLabels,
    LabelDef,
    save_document,
)
from app.mcp import tools_write


def _base_req() -> dict:
    return {
        "title": "T",
        "statement": "S",
        "type": "requirement",
        "status": "draft",
        "owner": "me",
        "priority": "low",
        "source": "spec",
        "verification": "analysis",
        "labels": [],
    }


def test_create_update_delete(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc"))
    res = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())
    assert res["rid"] == "SYS1"
    assert res["revision"] == 1
    res2 = tools_write.update_requirement_field(
        tmp_path,
        "SYS1",
        field="title",
        value="N",
    )
    assert res2["title"] == "N"
    assert res2["revision"] == 2
    res3 = tools_write.delete_requirement(tmp_path, "SYS1")
    assert res3 == {"rid": "SYS1"}


def test_delete_requirement_reports_revision_error(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc"))
    created = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())
    item_file = tmp_path / "SYS" / "items" / "1.json"
    payload = json.loads(item_file.read_text(encoding="utf-8"))
    payload["revision"] = 0
    item_file.write_text(json.dumps(payload), encoding="utf-8")

    result = tools_write.delete_requirement(tmp_path, created["rid"])
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert "revision" in result["error"]["message"].lower()


def test_update_rejects_prefix_case_mismatch(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc"))
    created = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())

    result = tools_write.update_requirement_field(
        tmp_path,
        created["rid"].lower(),
        field="title",
        value="Renamed",
    )

    assert result["error"]["code"] == "NOT_FOUND"
    assert created["rid"].lower() in result["error"]["message"]


def test_create_rejects_unknown_label(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc"))
    res = tools_write.create_requirement(
        tmp_path, prefix="SYS", data={**_base_req(), "labels": ["bad"]}
    )
    assert res["error"]["code"] == "VALIDATION_ERROR"


def test_create_rejects_string_labels(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc"))
    res = tools_write.create_requirement(
        tmp_path, prefix="SYS", data={**_base_req(), "labels": "oops"}
    )
    assert res["error"]["code"] == "VALIDATION_ERROR"


def test_create_accepts_inherited_label(tmp_path: Path) -> None:
    save_document(
        tmp_path / "SYS",
        Document(
            prefix="SYS",
            title="Doc",
            labels=DocumentLabels(defs=[LabelDef("ui", "UI")]),
        ),
    )
    save_document(
        tmp_path / "HLR",
        Document(prefix="HLR", title="H", parent="SYS"),
    )
    res = tools_write.create_requirement(
        tmp_path, prefix="HLR", data={**_base_req(), "labels": ["ui"]}
    )
    assert res["rid"] == "HLR1"
    assert res["labels"] == ["ui"]


def test_set_labels_rejects_unknown_label(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc"))
    created = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())
    res = tools_write.set_requirement_labels(tmp_path, created["rid"], ["bad"])
    assert res["error"]["code"] == "VALIDATION_ERROR"


def test_set_labels_rejects_string_payload(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc"))
    created = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())
    res = tools_write.set_requirement_labels(tmp_path, created["rid"], "oops")
    assert res["error"]["code"] == "VALIDATION_ERROR"


def test_set_labels_accepts_inherited_label(tmp_path: Path) -> None:
    save_document(
        tmp_path / "SYS",
        Document(
            prefix="SYS",
            title="Doc",
            labels=DocumentLabels(defs=[LabelDef("ui", "UI")]),
        ),
    )
    created = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())
    res = tools_write.set_requirement_labels(tmp_path, created["rid"], ["ui"])
    assert res["labels"] == ["ui"]


def test_set_attachments_rejects_string_payload(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc"))
    created = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())

    res = tools_write.set_requirement_attachments(tmp_path, created["rid"], "oops")

    assert res["error"]["code"] == "VALIDATION_ERROR"


def test_link_requirements(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc"))
    save_document(
        tmp_path / "HLR",
        Document(prefix="HLR", title="H", parent="SYS"),
    )
    parent = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())
    child = tools_write.create_requirement(tmp_path, prefix="HLR", data=_base_req())
    linked = tools_write.link_requirements(
        tmp_path,
        source_rid=parent["rid"],
        derived_rid=child["rid"],
        link_type="parent",
    )
    assert any(entry["rid"] == parent["rid"] for entry in linked["links"])


def test_link_requirements_rejects_invalid_type(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc"))
    save_document(
        tmp_path / "HLR",
        Document(prefix="HLR", title="H", parent="SYS"),
    )
    parent = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())
    child = tools_write.create_requirement(tmp_path, prefix="HLR", data=_base_req())
    res = tools_write.link_requirements(
        tmp_path,
        source_rid=parent["rid"],
        derived_rid=child["rid"],
        link_type="child",
    )
    assert res["error"]["code"] == "VALIDATION_ERROR"


def test_set_links_rejects_string_payload(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc"))
    created = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())

    res = tools_write.set_requirement_links(tmp_path, created["rid"], "oops")

    assert res["error"]["code"] == "VALIDATION_ERROR"
