from pathlib import Path

from app.core.doc_store import Document, save_document
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
    patch = [{"op": "replace", "path": "/title", "value": "N"}]
    res2 = tools_write.patch_requirement(tmp_path, "SYS001", patch, rev=1)
    assert res2["title"] == "N"
    assert res2["revision"] == 2
    res3 = tools_write.delete_requirement(tmp_path, "SYS001", rev=2)
    assert res3 == {"rid": "SYS001"}


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
    assert parent["rid"] in linked["links"]
