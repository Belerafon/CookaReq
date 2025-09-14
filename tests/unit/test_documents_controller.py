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
    assert [r.id for r in model.get_all()] == [1]
    labels, freeform = controller.collect_labels("SYS")
    assert freeform is True
    assert labels and labels[0].name == "ui" and labels[0].color == "#123456"


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
    controller.add_requirement(req)
    controller.save_requirement("SYS", req)
    path = doc_dir / "items" / "SYS001.json"
    assert path.is_file()

    controller.delete_requirement("SYS", req.id)
    assert not path.exists()
