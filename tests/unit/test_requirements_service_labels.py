from pathlib import Path

import pytest

from app.core.document_store import Document, DocumentLabels, LabelDef
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


def test_update_document_labels_renames_with_propagation(tmp_path: Path) -> None:
    root = tmp_path
    doc = Document(
        prefix="SYS",
        title="System",
        labels=DocumentLabels(defs=[LabelDef("legacy", "Legacy", "#112233")]),
    )
    save_document(root / "SYS", doc)
    requirement = _base_requirement("SYS")
    requirement.labels = ["legacy"]
    save_item(root / "SYS", doc, requirement.to_mapping())

    service = RequirementsService(root)
    service.update_document_labels(
        "SYS",
        original=[LabelDef("legacy", "Legacy", "#112233")],
        updated=[LabelDef("modern", "Modern", "#445566")],
        rename_choices={"legacy": ("modern", True)},
        removal_choices={},
    )

    refreshed = service.get_requirement("SYS1")
    assert refreshed.labels == ["modern"]
    doc_refreshed = service.get_document("SYS")
    assert [definition.key for definition in doc_refreshed.labels.defs] == ["modern"]


def test_update_label_definition_propagates_to_descendants(tmp_path: Path) -> None:
    root = tmp_path
    parent = Document(
        prefix="SYS",
        title="System",
        labels=DocumentLabels(defs=[LabelDef("SA", "Safety", "#224466")]),
    )
    child = Document(
        prefix="HLR",
        title="High level",
        parent="SYS",
        labels=DocumentLabels(defs=[LabelDef("SA", "Subsystem Safety", "#abcdef")]),
    )

    service = RequirementsService(root)
    service.save_document(parent)
    service.save_document(child)

    parent_req = _base_requirement("SYS")
    parent_req.labels = ["SA"]
    save_item(root / "SYS", parent, parent_req.to_mapping())

    child_req = _base_requirement("HLR")
    child_req.labels = ["SA"]
    save_item(root / "HLR", child, child_req.to_mapping())

    service.update_label_definition("SYS", key="SA", new_key="SAFE", propagate=True)

    refreshed_parent = service.get_document("SYS")
    assert [definition.key for definition in refreshed_parent.labels.defs] == ["SAFE"]

    refreshed_child = service.get_document("HLR")
    assert [definition.key for definition in refreshed_child.labels.defs] == ["SAFE"]
    assert refreshed_child.labels.defs[0].color == "#abcdef"

    defs, _ = service.collect_label_defs("HLR")
    assert all(definition.key != "SA" for definition in defs)

    assert service.get_requirement("SYS1").labels == ["SAFE"]
    assert service.get_requirement("HLR1").labels == ["SAFE"]


def test_update_label_definition_without_propagation_keeps_descendants(tmp_path: Path) -> None:
    root = tmp_path
    parent = Document(
        prefix="SYS",
        title="System",
        labels=DocumentLabels(defs=[LabelDef("SA", "Safety", "#224466")]),
    )
    child = Document(
        prefix="HLR",
        title="High level",
        parent="SYS",
        labels=DocumentLabels(defs=[LabelDef("SA", "Subsystem Safety", "#abcdef")]),
    )

    service = RequirementsService(root)
    service.save_document(parent)
    service.save_document(child)

    child_req = _base_requirement("HLR")
    child_req.labels = ["SA"]
    save_item(root / "HLR", child, child_req.to_mapping())

    service.update_label_definition("SYS", key="SA", new_key="SAFE", propagate=False)

    refreshed_child = service.get_document("HLR")
    assert [definition.key for definition in refreshed_child.labels.defs] == ["SA"]

    defs, _ = service.collect_label_defs("HLR")
    assert any(definition.key == "SA" for definition in defs)
    assert any(definition.key == "SAFE" for definition in defs)

    assert service.get_requirement("HLR1").labels == ["SA"]


def test_update_document_labels_rename_without_propagation(tmp_path: Path) -> None:
    root = tmp_path
    doc = Document(
        prefix="SYS",
        title="System",
        labels=DocumentLabels(defs=[LabelDef("legacy", "Legacy", None)]),
    )
    save_document(root / "SYS", doc)
    requirement = _base_requirement("SYS")
    requirement.labels = ["legacy"]
    save_item(root / "SYS", doc, requirement.to_mapping())

    service = RequirementsService(root)
    service.update_document_labels(
        "SYS",
        original=[LabelDef("legacy", "Legacy", None)],
        updated=[LabelDef("modern", "Modern", None)],
        rename_choices={"legacy": ("modern", False)},
        removal_choices={},
    )

    refreshed = service.get_requirement("SYS1")
    assert refreshed.labels == ["legacy"]
    doc_refreshed = service.get_document("SYS")
    assert [definition.key for definition in doc_refreshed.labels.defs] == ["modern"]


def test_update_document_labels_removal_cleans_requirements(tmp_path: Path) -> None:
    root = tmp_path
    doc = Document(
        prefix="SYS",
        title="System",
        labels=DocumentLabels(defs=[LabelDef("obsolete", "Obsolete", None)]),
    )
    save_document(root / "SYS", doc)
    requirement = _base_requirement("SYS")
    requirement.labels = ["obsolete"]
    save_item(root / "SYS", doc, requirement.to_mapping())

    service = RequirementsService(root)
    service.update_document_labels(
        "SYS",
        original=[LabelDef("obsolete", "Obsolete", None)],
        updated=[],
        rename_choices={},
        removal_choices={"obsolete": True},
    )

    refreshed = service.get_requirement("SYS1")
    assert refreshed.labels == []
    assert service.get_document("SYS").labels.defs == []


def test_describe_label_definitions_includes_inheritance(tmp_path: Path) -> None:
    root = tmp_path
    parent = Document(
        prefix="SYS",
        title="System",
        labels=DocumentLabels(defs=[LabelDef("core", "Core", "#111111")]),
    )
    child = Document(prefix="SW", title="Software", parent="SYS")
    save_document(root / "SYS", parent)
    save_document(root / "SW", child)

    service = RequirementsService(root)
    listing = service.describe_label_definitions("SW")

    assert listing["prefix"] == "SW"
    assert listing["effective_allow_freeform"] is False
    labels = listing["labels"]
    assert any(entry["key"] == "core" and entry["defined_in"] == "SYS" for entry in labels)
