from pathlib import Path

import pytest

from app.core.document_store import Document, DocumentLabels
from app.core.document_store.documents import load_document, save_document
from app.core.document_store.items import save_item
from app.core.model import Requirement, RequirementType, Status, Priority, Verification
from app.services.requirements import RequirementsService, ValidationError

pytestmark = pytest.mark.unit


def _base_requirement(prefix: str, *, req_id: int = 1) -> Requirement:
    return Requirement(
        id=req_id,
        title="Title",
        statement="Body",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="owner",
        priority=Priority.MEDIUM,
        source="source",
        verification=Verification.ANALYSIS,
        doc_prefix=prefix,
        rid=f"{prefix}{req_id}",
    )


def test_set_labels_promotes_new_definitions(tmp_path: Path) -> None:
    root = tmp_path
    doc = Document(prefix="SYS", title="System", labels=DocumentLabels(allow_freeform=True))
    save_document(root / "SYS", doc)
    requirement = _base_requirement("SYS")
    save_item(root / "SYS", doc, requirement.to_mapping())

    service = RequirementsService(root)
    updated = service.set_requirement_labels("SYS1", ["alpha_tag", "beta"])

    assert updated.labels == ["alpha_tag", "beta"]
    refreshed = service.get_document("SYS")
    keys = [definition.key for definition in refreshed.labels.defs]
    assert "alpha_tag" in keys
    promoted = next(defn for defn in refreshed.labels.defs if defn.key == "alpha_tag")
    assert promoted.title == "Alpha Tag"
    assert promoted.color.startswith("#")

    stored = load_document(root / "SYS")
    assert any(defn.key == "beta" for defn in stored.labels.defs)


def test_sync_labels_from_requirements_promotes_existing_usage(tmp_path: Path) -> None:
    root = tmp_path
    doc = Document(prefix="SYS", title="System", labels=DocumentLabels(allow_freeform=True))
    save_document(root / "SYS", doc)
    requirement = _base_requirement("SYS")
    requirement.labels = ["legacy", "color"]
    save_item(root / "SYS", doc, requirement.to_mapping())

    service = RequirementsService(root)
    promoted = service.sync_labels_from_requirements("SYS")

    assert {definition.key for definition in promoted} == {"legacy", "color"}
    refreshed = service.get_document("SYS")
    keys = {definition.key for definition in refreshed.labels.defs}
    assert {"legacy", "color"}.issubset(keys)


def test_set_labels_uses_nearest_freeform_ancestor(tmp_path: Path) -> None:
    root = tmp_path
    parent = Document(prefix="SYS", title="System", labels=DocumentLabels(allow_freeform=True))
    child = Document(prefix="SW", title="Software", parent="SYS")
    save_document(root / "SYS", parent)
    save_document(root / "SW", child)
    requirement = _base_requirement("SW")
    save_item(root / "SW", child, requirement.to_mapping())

    service = RequirementsService(root)
    service.set_requirement_labels("SW1", ["ui_ready"])

    parent_doc = service.get_document("SYS")
    assert any(defn.key == "ui_ready" for defn in parent_doc.labels.defs)
    child_doc = service.get_document("SW")
    assert not any(defn.key == "ui_ready" for defn in child_doc.labels.defs)


def test_set_labels_rejects_invalid_rid(tmp_path: Path) -> None:
    save_document(tmp_path / "SYS", Document(prefix="SYS", title="System"))
    service = RequirementsService(tmp_path)
    with pytest.raises(ValidationError):
        service.set_requirement_labels("@@@", [])


def test_set_labels_respects_disabled_freeform(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", doc)
    save_item(tmp_path / "SYS", doc, _base_requirement("SYS").to_mapping())

    service = RequirementsService(tmp_path)
    with pytest.raises(ValidationError):
        service.set_requirement_labels("SYS1", ["new_label"])

    persisted = load_document(tmp_path / "SYS")
    assert all(defn.key != "new_label" for defn in persisted.labels.defs)
