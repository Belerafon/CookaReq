import pytest
from pathlib import Path

import json

from app.services.requirements import RequirementsService
from app.ui.controllers.documents import DocumentsController
from app.ui.requirement_model import RequirementModel
from app.core.document_store import (
    Document,
    DocumentLabels,
    LabelDef,
    RequirementIDCollisionError,
    ValidationError,
    item_path,
    load_document,
    save_document,
    save_item,
    load_item,
)
from app.core.document_store.documents import get_document_revision
from app.core.model import (
    Requirement,
    RequirementType,
    Status,
    Priority,
    Verification,
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
        labels=DocumentLabels(
            allow_freeform=True,
            defs=[LabelDef(key="ui", title="UI", color="#123456")],
        ),
    )
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    save_item(doc_dir, doc, _req(1).to_mapping())

    model = RequirementModel()
    controller = _controller(tmp_path, model)
    docs = controller.load_documents()
    assert "SYS" in docs
    derived = controller.load_items("SYS")
    assert derived == {}
    all_reqs = model.get_all()
    assert [r.id for r in all_reqs] == [1]
    assert all_reqs[0].doc_prefix == "SYS"
    assert all_reqs[0].rid == "SYS1"
    labels, freeform = controller.collect_labels("SYS")
    assert freeform is True
    assert labels and labels[0].key == "ui" and labels[0].color == "#123456"


def test_sync_labels_from_requirements_refreshes_cache(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System", labels=DocumentLabels(allow_freeform=True))
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = _req(1)
    requirement.labels = ["legacy"]
    save_item(doc_dir, doc, requirement.to_mapping())

    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    promoted = controller.sync_labels_from_requirements("SYS")

    assert [definition.key for definition in promoted] == ["legacy"]
    refreshed = controller.documents["SYS"]
    assert any(defn.key == "legacy" for defn in refreshed.labels.defs)


def test_next_id_save_and_delete(tmp_path: Path):
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)

    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()

    new_id = controller.next_item_id("SYS")
    assert new_id == 1
    req = _req(new_id)
    controller.add_requirement("SYS", req)
    controller.save_requirement("SYS", req)
    path = item_path(doc_dir, doc, 1)
    assert path.is_file()
    assert req.doc_prefix == "SYS"
    assert req.rid == "SYS1"

    deleted = controller.delete_requirement("SYS", req.id)
    assert deleted == "SYS1"
    assert not path.exists()


def test_add_requirement_rejects_duplicate_id(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    save_item(doc_dir, doc, _req(1).to_mapping())

    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    controller.load_items("SYS")

    duplicate = _req(1)
    with pytest.raises(RequirementIDCollisionError):
        controller.add_requirement("SYS", duplicate)


def test_save_requirement_rejects_duplicate_id(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    save_item(doc_dir, doc, _req(1).to_mapping())
    save_item(doc_dir, doc, _req(2).to_mapping())

    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    controller.load_items("SYS")

    existing = model.get_all()[0]
    assert existing.id == 1
    existing.id = 2

    with pytest.raises(RequirementIDCollisionError):
        controller.save_requirement("SYS", existing)


def test_save_requirement_increments_revision_only_for_statement_changes(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)

    original = _req(1)
    original.revision = 1
    save_item(doc_dir, doc, original.to_mapping())

    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    controller.load_items("SYS")
    loaded = model.get_all()[0]

    loaded.title = "Changed title"
    controller.save_requirement("SYS", loaded)
    data_after_title, _ = load_item(doc_dir, doc, 1)
    assert data_after_title["revision"] == 1
    assert get_document_revision(load_document(doc_dir)) == 1

    loaded.statement = "Changed statement"
    controller.save_requirement("SYS", loaded)
    data_after_statement, _ = load_item(doc_dir, doc, 1)
    assert data_after_statement["revision"] == 2
    assert get_document_revision(load_document(doc_dir)) == 2


def test_iter_links(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System")
    hlr_doc = Document(prefix="HLR", title="High", parent="SYS")
    sys_dir = tmp_path / "SYS"
    hlr_dir = tmp_path / "HLR"
    save_document(sys_dir, sys_doc)
    save_document(hlr_dir, hlr_doc)
    save_item(sys_dir, sys_doc, _req(1).to_mapping())
    data = _req(1).to_mapping()
    data["links"] = ["SYS1"]
    save_item(hlr_dir, hlr_doc, data)
    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    links = list(controller.iter_links())
    assert ("HLR1", "SYS1") in links


def test_delete_requirement_removes_links(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System")
    hlr_doc = Document(prefix="HLR", title="High", parent="SYS")
    sys_dir = tmp_path / "SYS"
    hlr_dir = tmp_path / "HLR"
    save_document(sys_dir, sys_doc)
    save_document(hlr_dir, hlr_doc)
    save_item(sys_dir, sys_doc, _req(1).to_mapping())
    data = _req(1).to_mapping()
    data["links"] = ["SYS1"]
    save_item(hlr_dir, hlr_doc, data)
    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    deleted = controller.delete_requirement("SYS", 1)
    assert deleted == "SYS1"
    assert not item_path(sys_dir, sys_doc, 1).exists()
    data2, _ = load_item(hlr_dir, hlr_doc, 1)
    assert data2.get("links") in (None, [])


def test_delete_requirement_with_invalid_revision(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    save_item(doc_dir, doc, _req(1).to_mapping())

    path = item_path(doc_dir, doc, 1)
    data = json.loads(path.read_text(encoding="utf-8"))

    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    controller.load_items("SYS")

    data["revision"] = 0
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValidationError) as excinfo:
        controller.delete_requirement("SYS", 1)
    assert "revision" in str(excinfo.value).lower()
    assert path.exists()


def test_delete_document_recursively(tmp_path: Path):
    sys_doc = Document(prefix="SYS", title="System")
    hlr_doc = Document(prefix="HLR", title="High", parent="SYS")
    llr_doc = Document(prefix="LLR", title="Low", parent="HLR")
    sys_dir = tmp_path / "SYS"
    hlr_dir = tmp_path / "HLR"
    llr_dir = tmp_path / "LLR"
    save_document(sys_dir, sys_doc)
    save_document(hlr_dir, hlr_doc)
    save_document(llr_dir, llr_doc)
    save_item(sys_dir, sys_doc, _req(1).to_mapping())
    save_item(hlr_dir, hlr_doc, _req(1).to_mapping())
    save_item(llr_dir, llr_doc, _req(1).to_mapping())
    model = RequirementModel()
    controller = _controller(tmp_path, model)
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
    controller = _controller(tmp_path, model)
    controller.load_documents()
    created = controller.create_document("SYS", "System")
    assert created.prefix == "SYS"
    path = tmp_path / "SYS" / "document.json"
    assert path.is_file()
    stored = load_document(tmp_path / "SYS")
    assert stored.title == "System"
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    assert data == {
        "title": "System",
        "parent": None,
        "labels": {"allowFreeform": False, "defs": []},
        "attributes": {},
    }


def test_create_document_with_parent(tmp_path: Path) -> None:
    parent_doc = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", parent_doc)
    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    child = controller.create_document("HLR", "High", parent="SYS")
    assert child.parent == "SYS"
    stored_child = load_document(tmp_path / "HLR")
    assert stored_child.parent == "SYS"


def test_create_document_rejects_invalid_prefix(tmp_path: Path) -> None:
    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    with pytest.raises(ValueError):
        controller.create_document("sys", "System")


def test_create_document_rejects_duplicate(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", doc)
    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    with pytest.raises(ValueError):
        controller.create_document("SYS", "Another")


def test_rename_document_updates_metadata(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", doc)
    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    updated = controller.rename_document("SYS", title="Updated")
    assert updated.title == "Updated"
    stored = load_document(tmp_path / "SYS")
    assert stored.title == "Updated"


def test_rename_document_rejects_unknown(tmp_path: Path) -> None:
    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    with pytest.raises(ValueError):
        controller.rename_document("SYS", title="Missing")


def test_rename_document_updates_parent(tmp_path: Path) -> None:
    root = Document(prefix="ROOT", title="Root")
    child = Document(prefix="CH", title="Child", parent="ROOT")
    target = Document(prefix="NEW", title="New Parent")
    save_document(tmp_path / "ROOT", root)
    save_document(tmp_path / "CH", child)
    save_document(tmp_path / "NEW", target)
    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    updated = controller.rename_document("CH", parent="NEW")
    assert updated.parent == "NEW"
    stored = load_document(tmp_path / "CH")
    assert stored.parent == "NEW"


def test_rename_document_rejects_descendant_as_parent(tmp_path: Path) -> None:
    root = Document(prefix="ROOT", title="Root")
    child = Document(prefix="CH", title="Child", parent="ROOT")
    grand = Document(prefix="SUB", title="Sub", parent="CH")
    save_document(tmp_path / "ROOT", root)
    save_document(tmp_path / "CH", child)
    save_document(tmp_path / "SUB", grand)
    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    with pytest.raises(ValueError):
        controller.rename_document("ROOT", parent="CH")


def test_rename_document_rejects_missing_parent(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", doc)
    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    with pytest.raises(ValueError):
        controller.rename_document("SYS", parent="MISSING")


def test_rename_document_without_changes_returns_existing(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", doc)
    model = RequirementModel()
    controller = _controller(tmp_path, model)
    controller.load_documents()
    unchanged = controller.rename_document("SYS")
    assert unchanged.title == "System"
def _controller(root: Path, model: RequirementModel) -> DocumentsController:
    return DocumentsController(RequirementsService(root), model)
