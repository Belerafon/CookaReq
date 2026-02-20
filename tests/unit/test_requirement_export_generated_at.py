from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from app.core.document_store import Document, save_document, save_item
from app.core.model import Priority, Requirement, RequirementType, Status, Verification
from app.core.requirement_export import build_requirement_export, render_requirements_markdown

pytestmark = pytest.mark.unit


def test_render_requirements_markdown_formats_generated_timestamp_for_humans(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System", attributes={"doc_revision": 7})
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=10,
        title="Timestamp",
        statement="Body",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="",
        priority=Priority.MEDIUM,
        source="",
        verification=Verification.ANALYSIS,
        attachments=[],
        doc_prefix="SYS",
        rid="SYS10",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    export.generated_at = datetime.datetime(2026, 2, 10, 7, 5, 3, 1866, tzinfo=datetime.UTC)

    markdown = render_requirements_markdown(export)

    assert "Generated at 2026-02-10 07:05:03+00:00" in markdown
    assert "Document revisions: SYS rev 7" in markdown
    assert "## System (SYS, rev 7)" in markdown
    assert "T07:05:03" not in markdown
    assert "07:05:03.001866" not in markdown
