import pytest
from pathlib import Path

from app.ui.controllers.documents import DocumentsController
from app.ui.requirement_model import RequirementModel
from app.core.document_store import (
    Document,
    DocumentLabels,
    LabelDef,
    RequirementIDCollisionError,
    item_path,
    load_document,
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
    path = item_path(doc_dir, doc, 1)
    assert path.is_file()
    assert req.doc_prefix == "SYS"
    assert req.rid == "SYS001"

    controller.delete_requirement("SYS", req.id)
    assert not path.exists()


def test_add_requirement_rejects_duplicate_id(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System", digits=3)
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    save_item(doc_dir, doc, requirement_to_dict(_req(1)))

    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    controller.load_documents()
    controller.load_items("SYS")

    duplicate = _req(1)
    with pytest.raises(RequirementIDCollisionError):
        controller.add_requirement("SYS", duplicate)


def test_save_requirement_rejects_duplicate_id(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System", digits=3)
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    save_item(doc_dir, doc, requirement_to_dict(_req(1)))
    save_item(doc_dir, doc, requirement_to_dict(_req(2)))

    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    controller.load_documents()
    controller.load_items("SYS")

    existing = model.get_all()[0]
    assert existing.id == 1
    existing.id = 2

    with pytest.raises(RequirementIDCollisionError):
        controller.save_requirement("SYS", existing)


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
    assert not item_path(sys_dir, sys_doc, 1).exists()
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


def test_create_document_persists_configuration(tmp_path: Path) -> None:
    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    controller.load_documents()
    created = controller.create_document("SYS", "System", digits=4)
    assert created.prefix == "SYS"
    assert created.digits == 4
    path = tmp_path / "SYS" / "document.json"
    assert path.is_file()
    stored = load_document(tmp_path / "SYS")
    assert stored.title == "System"
    assert stored.digits == 4


def test_create_document_with_parent(tmp_path: Path) -> None:
    parent_doc = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", parent_doc)
    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    controller.load_documents()
    child = controller.create_document("HLR", "High", parent="SYS")
    assert child.parent == "SYS"
    stored_child = load_document(tmp_path / "HLR")
    assert stored_child.parent == "SYS"


def test_create_document_rejects_invalid_prefix(tmp_path: Path) -> None:
    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    controller.load_documents()
    with pytest.raises(ValueError):
        controller.create_document("sys", "System")


def test_create_document_rejects_duplicate(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc)
    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    controller.load_documents()
    with pytest.raises(ValueError):
        controller.create_document("SYS", "Another")


def test_rename_document_updates_metadata(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc)
    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    controller.load_documents()
    updated = controller.rename_document("SYS", title="Updated", digits=5)
    assert updated.title == "Updated"
    assert updated.digits == 5
    stored = load_document(tmp_path / "SYS")
    assert stored.title == "Updated"
    assert stored.digits == 5


def test_rename_document_rejects_unknown(tmp_path: Path) -> None:
    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    controller.load_documents()
    with pytest.raises(ValueError):
        controller.rename_document("SYS", title="Missing")


def test_rename_document_rejects_invalid_digits(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc)
    model = RequirementModel()
    controller = DocumentsController(tmp_path, model)
    controller.load_documents()
    with pytest.raises(ValueError):
        controller.rename_document("SYS", digits=0)
