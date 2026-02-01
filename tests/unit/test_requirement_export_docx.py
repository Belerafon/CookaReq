from __future__ import annotations

import base64
import io
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.core.document_store import Document, save_document, save_item
from app.core.model import Attachment, Priority, Requirement, RequirementType, Status, Verification
from app.core.requirement_export import build_requirement_export, render_requirements_docx

pytestmark = pytest.mark.unit

_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/wwAAgMBAp0lP9sAAAAASUVORK5CYII="
)


def test_render_requirements_docx_embeds_assets(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    assets_dir = doc_dir / "assets"
    assets_dir.mkdir(parents=True)
    image_path = assets_dir / "diagram.png"
    image_path.write_bytes(_PNG_BYTES)
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=1,
        title="Title",
        statement="See ![Diagram](attachment:att-1)",
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
    payload = render_requirements_docx(export)

    assert payload
    with ZipFile(io.BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        assert "SYS1" in document_xml
        assert "Title" in document_xml
        media_files = [name for name in archive.namelist() if name.startswith("word/media/")]
        assert media_files


def test_render_requirements_docx_renders_tables(tmp_path: Path) -> None:
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
    payload = render_requirements_docx(export)

    with ZipFile(io.BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        assert "<w:tbl>" in document_xml
        assert "A" in document_xml
        assert "1" in document_xml


def test_render_requirements_docx_keeps_formula_text(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=3,
        title="Formula requirement",
        statement="Speed \\(v = s/t\\)",
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
    payload = render_requirements_docx(export, formula_renderer="text")

    with ZipFile(io.BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        assert "v = s/t" in document_xml


def test_render_requirements_docx_renders_formula_omml(tmp_path: Path) -> None:
    pytest.importorskip("latex2mathml")
    pytest.importorskip("mathml2omml")
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=4,
        title="Formula requirement",
        statement="Energy \\(E = mc^2\\)",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="owner",
        priority=Priority.MEDIUM,
        source="spec",
        verification=Verification.ANALYSIS,
        attachments=[],
        doc_prefix="SYS",
        rid="SYS4",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    payload = render_requirements_docx(export, formula_renderer="mathml")

    with ZipFile(io.BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        assert "<m:oMath" in document_xml
