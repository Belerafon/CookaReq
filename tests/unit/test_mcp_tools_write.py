import json
from pathlib import Path

from app.core.document_store import (
    Document,
    DocumentLabels,
    LabelDef,
    save_document,
)
from app.mcp import tools_read, tools_write


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
    assert res2["field_change"] == {
        "field": "title",
        "previous": "T",
        "current": "N",
    }
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


def test_set_labels_promotes_new_keys_across_updates(tmp_path: Path) -> None:
    save_document(
        tmp_path / "SYS",
        Document(
            prefix="SYS",
            title="Doc",
            labels=DocumentLabels(allow_freeform=True),
        ),
    )
    created = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())

    first = tools_write.set_requirement_labels(
        tmp_path, created["rid"], ["alpha_tag", "beta"]
    )
    assert first["labels"] == ["alpha_tag", "beta"]
    defs_after_first = _load_document_labels(tmp_path, "SYS")
    assert {entry["key"] for entry in defs_after_first} == {"alpha_tag", "beta"}
    alpha = next(entry for entry in defs_after_first if entry["key"] == "alpha_tag")
    assert alpha["title"] == "Alpha Tag"

    second = tools_write.set_requirement_labels(
        tmp_path, created["rid"], ["beta", "gamma_plus"]
    )
    assert second["labels"] == ["beta", "gamma_plus"]
    defs_after_second = _load_document_labels(tmp_path, "SYS")
    keys_after_second = {entry["key"] for entry in defs_after_second}
    assert {"alpha_tag", "beta", "gamma_plus"} == keys_after_second
    gamma = next(entry for entry in defs_after_second if entry["key"] == "gamma_plus")
    assert gamma["title"] == "Gamma Plus"
    assert sum(1 for entry in defs_after_second if entry["key"] == "beta") == 1

    cleared = tools_write.set_requirement_labels(tmp_path, created["rid"], [])
    assert cleared["labels"] == []
    defs_after_cleared = _load_document_labels(tmp_path, "SYS")
    assert {entry["key"] for entry in defs_after_cleared} == {
        "alpha_tag",
        "beta",
        "gamma_plus",
    }


def test_set_labels_promotes_to_freeform_ancestor(tmp_path: Path) -> None:
    save_document(
        tmp_path / "SYS",
        Document(
            prefix="SYS",
            title="Doc",
            labels=DocumentLabels(allow_freeform=True),
        ),
    )
    save_document(
        tmp_path / "SW",
        Document(prefix="SW", title="Software", parent="SYS"),
    )
    created = tools_write.create_requirement(tmp_path, prefix="SW", data=_base_req())

    result = tools_write.set_requirement_labels(tmp_path, created["rid"], ["ui_ready"])

    assert result["labels"] == ["ui_ready"]
    parent_defs = _load_document_labels(tmp_path, "SYS")
    assert any(entry["key"] == "ui_ready" for entry in parent_defs)
    child_defs = _load_document_labels(tmp_path, "SW")
    assert child_defs == []


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


def _load_document_labels(tmp_path: Path, prefix: str) -> list[dict]:
    data = json.loads((tmp_path / prefix / "document.json").read_text(encoding="utf-8"))
    return data.get("labels", {}).get("defs", [])


def _load_requirement_labels(tmp_path: Path, prefix: str, item_id: int) -> list[str]:
    path = tmp_path / prefix / "items" / f"{item_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("labels", [])


def test_create_label_registers_definition(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc"))

    result = tools_write.create_label(
        tmp_path,
        prefix="SYS",
        key="qa",
        title="Quality",
        color="#123456",
    )

    assert result == {"key": "qa", "title": "Quality", "color": "#123456"}
    defs = _load_document_labels(tmp_path, "SYS")
    assert any(entry["key"] == "qa" and entry["title"] == "Quality" for entry in defs)


def test_update_label_propagates_when_requested(tmp_path: Path) -> None:
    save_document(
        tmp_path / "SYS",
        Document(prefix="SYS", title="Doc", labels=DocumentLabels(defs=[LabelDef("legacy", "Legacy")])),
    )
    tools_write.create_requirement(
        tmp_path,
        prefix="SYS",
        data={**_base_req(), "labels": ["legacy"]},
    )

    res = tools_write.update_label(
        tmp_path,
        prefix="SYS",
        key="legacy",
        new_key="modern",
        title="Modern",
        propagate=True,
    )

    assert res["key"] == "modern"
    assert res["propagated"] is True
    assert _load_requirement_labels(tmp_path, "SYS", 1) == ["modern"]


def test_update_label_without_propagation_leaves_requirements(tmp_path: Path) -> None:
    save_document(
        tmp_path / "SYS",
        Document(prefix="SYS", title="Doc", labels=DocumentLabels(defs=[LabelDef("legacy", "Legacy")])),
    )
    tools_write.create_requirement(
        tmp_path,
        prefix="SYS",
        data={**_base_req(), "labels": ["legacy"]},
    )

    res = tools_write.update_label(
        tmp_path,
        prefix="SYS",
        key="legacy",
        new_key="modern",
        title="Modern",
        propagate=False,
    )

    assert res["key"] == "modern"
    assert res["propagated"] is False
    assert _load_requirement_labels(tmp_path, "SYS", 1) == ["legacy"]


def test_delete_label_removes_from_requirements(tmp_path: Path) -> None:
    save_document(
        tmp_path / "SYS",
        Document(prefix="SYS", title="Doc", labels=DocumentLabels(defs=[LabelDef("obsolete", "Obsolete")])),
    )
    tools_write.create_requirement(
        tmp_path,
        prefix="SYS",
        data={**_base_req(), "labels": ["obsolete"]},
    )

    res = tools_write.delete_label(
        tmp_path,
        prefix="SYS",
        key="obsolete",
        remove_from_requirements=True,
    )

    assert res == {"removed": True, "key": "obsolete"}
    assert _load_document_labels(tmp_path, "SYS") == []
    assert _load_requirement_labels(tmp_path, "SYS", 1) == []


def test_list_labels_reports_inheritance(tmp_path: Path) -> None:
    save_document(
        tmp_path / "SYS",
        Document(
            prefix="SYS",
            title="System",
            labels=DocumentLabels(defs=[LabelDef("core", "Core", "#010101")]),
        ),
    )
    save_document(
        tmp_path / "SW",
        Document(
            prefix="SW",
            title="Software",
            parent="SYS",
            labels=DocumentLabels(defs=[LabelDef("child", "Child")]),
        ),
    )

    payload = tools_read.list_labels(tmp_path, prefix="SW")

    assert payload["prefix"] == "SW"
    keys = {entry["key"]: entry for entry in payload["labels"]}
    assert "core" in keys and keys["core"]["defined_in"] == "SYS"
    assert "child" in keys and keys["child"]["defined_in"] == "SW"
