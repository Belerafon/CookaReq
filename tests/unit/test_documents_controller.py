import pytest
from pathlib import Path

from app.ui.controllers.documents import DocumentsController
from app.ui.requirement_model import RequirementModel
from app.core.doc_store import (
    Document,
    DocumentLabels,
    LabelDef,
    save_document,
    save_item,
    load_item,
)
from app.core.model import (
    Requirement,
    RequirementType,
    Status,
    Priority,
    Verification,
    requirement_to_dict,
)

pytestmark = pytest.mark.unit


def _req(req_id: int) -> Requirement:
    return Requirement(
        id=req_id,
        title="T",
        statement="S",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="o",
        priority=Priority.MEDIUM,
        source="s",
        verification=Verification.ANALYSIS,
    )


def test_load_documents_and_items(tmp_path: Path):
    doc = Document(
        prefix="SYS",
        title="System",
        digits=3,
        labels=DocumentLabels(
            allow_freeform=True,
            defs=[LabelDef(key="ui", title="UI", color="#123456")],
        ),
    )
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    save_item(doc_dir, doc, requirement_to_dict(_req(1)))

    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    docs = controller.load_documents()
    assert "SYS" in docs
    derived = controller.load_items("SYS")
    assert derived == {}
    all_reqs = model.get_all()
    assert [r.id for r in all_reqs] == [1]
    assert all_reqs[0].doc_prefix == "SYS"
    assert all_reqs[0].rid == "SYS001"
    labels, freeform = controller.collect_labels("SYS")
    assert freeform is True
    assert labels and labels[0].key == "ui" and labels[0].color == "#123456"


def test_next_id_save_and_delete(tmp_path: Path):
    doc = Document(prefix="SYS", title="System", digits=3)
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)

    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    controller.load_documents()

    new_id = controller.next_item_id("SYS")
    assert new_id == 1
    req = _req(new_id)
    controller.add_requirement("SYS", req)
    controller.save_requirement("SYS", req)
    path = doc_dir / "items" / "SYS001.json"
    assert path.is_file()
    assert req.doc_prefix == "SYS"
    assert req.rid == "SYS001"

    controller.delete_requirement("SYS", req.id)
    assert not path.exists()


def test_iter_links(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System", digits=3)
    hlr_doc = Document(prefix="HLR", title="High", digits=3, parent="SYS")
    sys_dir = tmp_path / "SYS"
    hlr_dir = tmp_path / "HLR"
    save_document(sys_dir, sys_doc)
    save_document(hlr_dir, hlr_doc)
    save_item(sys_dir, sys_doc, requirement_to_dict(_req(1)))
    data = requirement_to_dict(_req(1))
    data["links"] = ["SYS001"]
    save_item(hlr_dir, hlr_doc, data)
    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    controller.load_documents()
    links = list(controller.iter_links())
    assert ("HLR001", "SYS001") in links


def test_delete_requirement_removes_links(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System", digits=3)
    hlr_doc = Document(prefix="HLR", title="High", digits=3, parent="SYS")
    sys_dir = tmp_path / "SYS"
    hlr_dir = tmp_path / "HLR"
    save_document(sys_dir, sys_doc)
    save_document(hlr_dir, hlr_doc)
    save_item(sys_dir, sys_doc, requirement_to_dict(_req(1)))
    data = requirement_to_dict(_req(1))
    data["links"] = ["SYS001"]
    save_item(hlr_dir, hlr_doc, data)
    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    controller.load_documents()
    controller.delete_requirement("SYS", 1)
    assert not (sys_dir / "items" / "SYS001.json").exists()
    data2, _ = load_item(hlr_dir, hlr_doc, 1)
    assert data2.get("links") == []


def test_delete_document_recursively(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System", digits=3)
    hlr_doc = Document(prefix="HLR", title="High", digits=3, parent="SYS")
    llr_doc = Document(prefix="LLR", title="Low", digits=3, parent="HLR")
    sys_dir = tmp_path / "SYS"
    hlr_dir = tmp_path / "HLR"
    llr_dir = tmp_path / "LLR"
    save_document(sys_dir, sys_doc)
    save_document(hlr_dir, hlr_doc)
    save_document(llr_dir, llr_doc)
    save_item(sys_dir, sys_doc, requirement_to_dict(_req(1)))
    save_item(hlr_dir, hlr_doc, requirement_to_dict(_req(1)))
    save_item(llr_dir, llr_doc, requirement_to_dict(_req(1)))
    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    controller.load_documents()
    controller.load_items("LLR")
    assert model.get_all()
    removed = controller.delete_document("HLR")
    assert removed is True
    assert "HLR" not in controller.documents
    assert "LLR" not in controller.documents
    assert not hlr_dir.exists()
    assert not llr_dir.exists()
    assert model.get_all() == []
