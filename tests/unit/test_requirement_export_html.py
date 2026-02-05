from __future__ import annotations

from pathlib import Path

import pytest

from app.core.document_store import Document, save_document, save_item
from app.core.model import Attachment, Priority, Requirement, RequirementType, Status, Verification
from app.core.requirement_export import build_requirement_export, render_requirements_html

pytestmark = pytest.mark.unit


def test_render_requirements_html_renders_markdown_and_attachments(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=1,
        title="Title",
        statement="See **bold** and ![Diagram](attachment:att-1) [bad](javascript:alert(1))",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="owner",
        priority=Priority.MEDIUM,
        source="spec",
        verification=Verification.ANALYSIS,
        attachments=[Attachment(id="att-1", path="assets/diagram.png", note="")],
        doc_prefix="SYS",
        rid="SYS1",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    html = render_requirements_html(export)

    assert "<strong>bold</strong>" in html
    assert "src=\"assets/diagram.png\"" in html
    assert "javascript:alert(1)" not in html


def test_render_requirements_html_renders_tables(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=2,
        title="Table requirement",
        statement="| A | B |\n|---|---|\n| 1 | 2 |",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="owner",
        priority=Priority.MEDIUM,
        source="spec",
        verification=Verification.ANALYSIS,
        attachments=[],
        doc_prefix="SYS",
        rid="SYS2",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    html = render_requirements_html(export)

    assert "<table>" in html
    assert "<td>1</td>" in html


def test_render_requirements_html_renders_formulas(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=3,
        title="Formula requirement",
        statement="Inline \\(E = mc^2\\) and block:\n$$\\frac{a}{b}$$",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="owner",
        priority=Priority.MEDIUM,
        source="spec",
        verification=Verification.ANALYSIS,
        attachments=[],
        doc_prefix="SYS",
        rid="SYS3",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    html = render_requirements_html(export)

    assert "<math" in html
    assert "\\(E = mc^2\\)" not in html


def test_render_requirements_html_shows_empty_fields_placeholder(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=4,
        title="Empty fields",
        statement="",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="",
        priority=Priority.MEDIUM,
        source="",
        verification=Verification.ANALYSIS,
        attachments=[],
        doc_prefix="SYS",
        rid="SYS4",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    html = render_requirements_html(export, empty_field_placeholder="(not set)")

    assert "<dt>Owner</dt><dd>(not set)</dd>" in html
    assert "<dt>Source</dt><dd>(not set)</dd>" in html
    assert "(not set)" in html


def test_render_requirements_html_hides_empty_rationale_without_placeholder(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=5,
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
        rid="SYS5",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    html = render_requirements_html(export)

    assert "(not provided)" not in html
    assert "<h4>Rationale</h4>" not in html


def test_render_requirements_html_respects_selected_fields(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=6,
        title="Filtered",
        statement="Important statement",
        rationale="Internal rationale",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="alice",
        priority=Priority.MEDIUM,
        source="spec",
        verification=Verification.ANALYSIS,
        attachments=[],
        doc_prefix="SYS",
        rid="SYS6",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    html = render_requirements_html(export, fields=["title", "statement"])

    assert "Important statement" in html
    assert "Internal rationale" not in html
    assert "<dt>Owner</dt>" not in html
