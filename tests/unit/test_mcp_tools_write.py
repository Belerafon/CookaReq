from pathlib import Path

from app.core.document_store import Document, DocumentLabels, LabelDef, save_document
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


def test_create_patch_delete(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc", digits=3))
    res = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())
    assert res["rid"] == "SYS001"
    assert res["revision"] == 1
    patch = [
        {"op": "replace", "path": "/title", "value": "N"},
        {"op": "replace", "path": "/revision", "value": 4},
    ]
    res2 = tools_write.patch_requirement(tmp_path, "SYS001", patch, rev=1)
    assert res2["title"] == "N"
    assert res2["revision"] == 4
    res3 = tools_write.delete_requirement(tmp_path, "SYS001", rev=4)
    assert res3 == {"rid": "SYS001"}


def test_create_rejects_unknown_label(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc", digits=3))
    res = tools_write.create_requirement(
        tmp_path, prefix="SYS", data={**_base_req(), "labels": ["bad"]}
    )
    assert res["error"]["code"] == "VALIDATION_ERROR"


def test_create_rejects_string_labels(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc", digits=3))
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
            digits=3,
            labels=DocumentLabels(defs=[LabelDef("ui", "UI")]),
        ),
    )
    save_document(
        tmp_path / "HLR",
        Document(prefix="HLR", title="H", digits=2, parent="SYS"),
    )
    res = tools_write.create_requirement(
        tmp_path, prefix="HLR", data={**_base_req(), "labels": ["ui"]}
    )
    assert res["rid"] == "HLR01"
    assert res["labels"] == ["ui"]


def test_patch_rejects_unknown_label(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc", digits=3))
    created = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())
    patch = [{"op": "replace", "path": "/labels", "value": ["bad"]}]
    res = tools_write.patch_requirement(tmp_path, created["rid"], patch, rev=1)
    assert res["error"]["code"] == "VALIDATION_ERROR"


def test_patch_rejects_string_labels(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc", digits=3))
    created = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())
    patch = [{"op": "replace", "path": "/labels", "value": "oops"}]
    res = tools_write.patch_requirement(tmp_path, created["rid"], patch, rev=1)
    assert res["error"]["code"] == "VALIDATION_ERROR"


def test_patch_accepts_inherited_label(tmp_path: Path) -> None:
    save_document(
        tmp_path / "SYS",
        Document(
            prefix="SYS",
            title="Doc",
            digits=3,
            labels=DocumentLabels(defs=[LabelDef("ui", "UI")]),
        ),
    )
    created = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())
    patch = [{"op": "replace", "path": "/labels", "value": ["ui"]}]
    res = tools_write.patch_requirement(tmp_path, created["rid"], patch, rev=1)
    assert res["labels"] == ["ui"]


def test_link_requirements(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc", digits=3))
    save_document(
        tmp_path / "HLR",
        Document(prefix="HLR", title="H", digits=3, parent="SYS"),
    )
    parent = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())
    child = tools_write.create_requirement(tmp_path, prefix="HLR", data=_base_req())
    linked = tools_write.link_requirements(
        tmp_path,
        source_rid=parent["rid"],
        derived_rid=child["rid"],
        link_type="parent",
        rev=1,
    )
    assert any(entry["rid"] == parent["rid"] for entry in linked["links"])


def test_link_requirements_rejects_invalid_type(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="Doc", digits=3))
    save_document(
        tmp_path / "HLR",
        Document(prefix="HLR", title="H", digits=3, parent="SYS"),
    )
    parent = tools_write.create_requirement(tmp_path, prefix="SYS", data=_base_req())
    child = tools_write.create_requirement(tmp_path, prefix="HLR", data=_base_req())
    res = tools_write.link_requirements(
        tmp_path,
        source_rid=parent["rid"],
        derived_rid=child["rid"],
        link_type="child",
        rev=1,
    )
    assert res["error"]["code"] == "VALIDATION_ERROR"
