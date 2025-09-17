import pytest
from pathlib import Path

from app.core.document_store import Document, save_document, save_item, load_item
from app.core.model import (
    Attachment,
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
    requirement_from_dict,
    requirement_to_dict,
)

pytestmark = pytest.mark.unit


def test_save_and_load_extended_fields(tmp_path: Path):
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    req = Requirement(
        id=1,
        title="T",
        statement="S",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="o",
        priority=Priority.MEDIUM,
        source="s",
        verification=Verification.ANALYSIS,
        attachments=[Attachment(path="file.txt", note="n")],
        approved_at="2024-01-01",
        notes="note",
        rationale="reason",
        assumptions="context",
    )
    save_item(doc_dir, doc, requirement_to_dict(req))
    data, _ = load_item(doc_dir, doc, 1)
    loaded = requirement_from_dict(data)
    assert loaded.attachments[0].path == "file.txt"
    assert loaded.approved_at == "2024-01-01"
    assert loaded.notes == "note"
    assert loaded.rationale == "reason"
    assert loaded.assumptions == "context"
