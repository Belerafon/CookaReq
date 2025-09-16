import pytest
from pathlib import Path

from app.core.document_store import Document, ValidationError
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
    requirement_to_dict,
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
    sys_doc = Document(prefix="SYS", title="System", digits=3)
    hlr_doc = Document(prefix="HLR", title="High level", digits=2, parent="SYS")
    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)

    save_item(tmp_path / "SYS", sys_doc, requirement_to_dict(_requirement(1)))
    child_data = requirement_to_dict(_requirement(1))
    child_data["links"] = []
    save_item(tmp_path / "HLR", hlr_doc, child_data)

    docs = load_documents(tmp_path)

    with pytest.raises(ValidationError):
        validate_item_links(
            tmp_path,
            hlr_doc,
            {"id": 1, "title": "H", "statement": "", "links": ["HLR01"]},
            docs,
        )

    linked = link_requirements(
        tmp_path,
        source_rid="SYS001",
        derived_rid="HLR01",
        link_type="parent",
        expected_revision=1,
        docs=docs,
    )
    assert linked.links == ["SYS001"]
    assert linked.revision == 2

    data, _ = load_item(tmp_path / "HLR", hlr_doc, 1)
    assert data["links"] == ["SYS001"]

    exists, references = plan_delete_item(tmp_path, "SYS001", docs)
    assert exists is True
    assert references == ["HLR01"]

    doc_prefixes, item_ids = plan_delete_document(tmp_path, "SYS", docs)
    assert set(doc_prefixes) == {"SYS", "HLR"}
    assert set(item_ids) == {"SYS001", "HLR01"}

    with pytest.raises(ValidationError):
        link_requirements(
            tmp_path,
            source_rid="SYS001",
            derived_rid="HLR01",
            link_type="child",
            expected_revision=2,
            docs=docs,
        )
