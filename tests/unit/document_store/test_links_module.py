import pytest
from pathlib import Path

from app.core.document_store import (
    Document,
    RequirementNotFoundError,
    ValidationError,
    get_requirement,
)
from app.core.document_store.documents import load_documents, save_document
from app.core.document_store.items import load_item, save_item
from app.core.document_store.links import (
    link_requirements,
    plan_delete_document,
    plan_delete_item,
    validate_item_links,
)
from app.core.model import (
    Requirement,
    RequirementType,
    Status,
    Priority,
    Verification,
    requirement_fingerprint,
)

pytestmark = pytest.mark.unit


def _requirement(req_id: int) -> Requirement:
    return Requirement(
        id=req_id,
        title=f"Requirement {req_id}",
        statement="Body",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="owner",
        priority=Priority.MEDIUM,
        source="source",
        verification=Verification.ANALYSIS,
    )


def test_validate_and_link(tmp_path: Path) -> None:
    sys_doc = Document(prefix="SYS", title="System")
    hlr_doc = Document(prefix="HLR", title="High level", parent="SYS")
    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)

    save_item(tmp_path / "SYS", sys_doc, _requirement(1).to_mapping())
    child_data = _requirement(1).to_mapping()
    child_data["links"] = []
    save_item(tmp_path / "HLR", hlr_doc, child_data)

    docs = load_documents(tmp_path)

    with pytest.raises(ValidationError):
        validate_item_links(
            tmp_path,
            hlr_doc,
            {"id": 1, "title": "H", "statement": "", "links": ["HLR1"]},
            docs,
        )

    linked = link_requirements(
        tmp_path,
        source_rid="SYS1",
        derived_rid="HLR1",
        link_type="parent",
        docs=docs,
    )
    assert len(linked.links) == 1
    link_obj = linked.links[0]
    assert link_obj.rid == "SYS1"
    assert link_obj.suspect is False
    assert isinstance(link_obj.fingerprint, str) and link_obj.fingerprint
    assert linked.revision == 1

    data, _ = load_item(tmp_path / "HLR", hlr_doc, 1)
    parent_data, _ = load_item(tmp_path / "SYS", sys_doc, 1)
    expected_fp = requirement_fingerprint(parent_data)
    assert data["links"] == [{"rid": "SYS1", "fingerprint": expected_fp}]

    exists, references = plan_delete_item(tmp_path, "SYS1", docs)
    assert exists is True
    assert references == ["HLR1"]

    doc_prefixes, item_ids = plan_delete_document(tmp_path, "SYS", docs)
    assert set(doc_prefixes) == {"SYS", "HLR"}
    assert set(item_ids) == {"SYS1", "HLR1"}

    with pytest.raises(ValidationError):
        link_requirements(
            tmp_path,
            source_rid="SYS1",
            derived_rid="HLR1",
            link_type="child",
            docs=docs,
        )


def test_link_rejects_mismatched_case_rids(tmp_path: Path) -> None:
    sys_doc = Document(prefix="SYS", title="System")
    hlr_doc = Document(prefix="HLR", title="High", parent="SYS")
    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)

    save_item(tmp_path / "SYS", sys_doc, _requirement(1).to_mapping())
    save_item(tmp_path / "HLR", hlr_doc, _requirement(2).to_mapping())

    docs = load_documents(tmp_path)

    with pytest.raises(RequirementNotFoundError) as exc:
        link_requirements(
            tmp_path,
            source_rid="sys1",
            derived_rid="hlr2",
            link_type="parent",
            docs=docs,
        )

    message = str(exc.value)
    assert "sys1" in message


def test_link_becomes_suspect_after_parent_change(tmp_path: Path) -> None:
    sys_doc = Document(prefix="SYS", title="System")
    hlr_doc = Document(prefix="HLR", title="High", parent="SYS")
    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)

    save_item(tmp_path / "SYS", sys_doc, _requirement(1).to_mapping())
    child_payload = _requirement(2).to_mapping()
    save_item(tmp_path / "HLR", hlr_doc, child_payload)

    docs = load_documents(tmp_path)
    linked = link_requirements(
        tmp_path,
        source_rid="SYS1",
        derived_rid="HLR2",
        link_type="parent",
        docs=docs,
    )
    assert linked.links[0].suspect is False

    child_data, _ = load_item(tmp_path / "HLR", hlr_doc, 2)
    stored_fp = child_data["links"][0]["fingerprint"]

    parent_data, _ = load_item(tmp_path / "SYS", sys_doc, 1)
    parent_data["statement"] = "Updated body"
    new_fp = requirement_fingerprint(parent_data)
    assert new_fp != stored_fp
    save_item(tmp_path / "SYS", sys_doc, parent_data)

    updated = get_requirement(tmp_path, "HLR2", docs=docs)
    link_obj = updated.links[0]
    assert link_obj.suspect is True
    assert link_obj.fingerprint == stored_fp

    serialized = updated.to_mapping()
    assert serialized["links"][0]["fingerprint"] == stored_fp
    assert serialized["links"][0]["suspect"] is True


def test_validate_item_links_reports_index(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", doc)
    docs = load_documents(tmp_path)
    data = {"id": 1, "title": "", "statement": "", "links": ["123"]}

    with pytest.raises(ValidationError) as excinfo:
        validate_item_links(tmp_path, doc, data, docs)

    message = str(excinfo.value)
    assert "links[0].rid" in message
    assert "123" in message
