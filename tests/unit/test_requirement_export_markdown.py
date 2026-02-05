from __future__ import annotations

from pathlib import Path

import pytest

from app.core.document_store import Document, save_document, save_item
from app.i18n import install
from app.core.model import Priority, Requirement, RequirementType, Status, Verification
from app.core.requirement_export import build_requirement_export, render_requirements_markdown

pytestmark = pytest.mark.unit


def test_render_requirements_markdown_shows_empty_fields_placeholder(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=1,
        title="Missing fields",
        statement="",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="",
        priority=Priority.MEDIUM,
        source="",
        verification=Verification.ANALYSIS,
        attachments=[],
        doc_prefix="SYS",
        rid="SYS1",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    markdown = render_requirements_markdown(export, empty_field_placeholder="(not set)")

    assert "- **Owner:** (not set)" in markdown
    assert "**Notes**" in markdown
    assert "(not set)" in markdown


def test_render_requirements_markdown_hides_empty_rationale_without_placeholder(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=2,
        title="No rationale",
        statement="Statement",
        rationale="",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="",
        priority=Priority.MEDIUM,
        source="",
        verification=Verification.ANALYSIS,
        attachments=[],
        doc_prefix="SYS",
        rid="SYS2",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    markdown = render_requirements_markdown(export)

    assert "(not provided)" not in markdown
    assert "**Rationale**" not in markdown


def test_render_requirements_markdown_localizes_enum_values(tmp_path: Path) -> None:
    install("CookaReq", "app/locale", ["ru"])
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=3,
        title="Localized",
        statement="Statement",
        type=RequirementType.REQUIREMENT,
        status=Status.APPROVED,
        owner="",
        priority=Priority.MEDIUM,
        source="",
        verification=Verification.ANALYSIS,
        attachments=[],
        doc_prefix="SYS",
        rid="SYS3",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    markdown = render_requirements_markdown(export)

    assert "- **Статус:** ``Согласовано``" in markdown
    assert "- **Приоритет исполнения:** ``Средний``" in markdown
    install("CookaReq", "app/locale", ["en"])
