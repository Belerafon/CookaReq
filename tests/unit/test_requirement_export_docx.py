from __future__ import annotations

import base64
import io
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.core.document_store import Document, DocumentLabels, LabelDef, save_document, save_item
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


def test_render_requirements_docx_shows_empty_fields_placeholder(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=4,
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
        rid="SYS4",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    payload = render_requirements_docx(export, empty_field_placeholder="(not set)")

    with ZipFile(io.BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        assert "Owner" in document_xml
        assert "(not set)" in document_xml


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


def test_render_requirements_docx_renders_formula_png(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=5,
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
        rid="SYS5",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    payload = render_requirements_docx(export, formula_renderer="png")

    with ZipFile(io.BytesIO(payload)) as archive:
        media_files = [name for name in archive.namelist() if name.startswith("word/media/")]
        assert media_files


def test_render_requirements_docx_renders_formula_svg(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    pytest.importorskip("cairosvg")
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=6,
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
        rid="SYS6",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    payload = render_requirements_docx(export, formula_renderer="svg")

    with ZipFile(io.BytesIO(payload)) as archive:
        media_files = [name for name in archive.namelist() if name.startswith("word/media/")]
        assert media_files


def test_render_requirements_docx_hides_empty_rationale_without_placeholder(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=7,
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
        rid="SYS7",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    payload = render_requirements_docx(export)

    with ZipFile(io.BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        assert "(not provided)" not in document_xml
        assert "Rationale" not in document_xml


def test_render_requirements_docx_respects_selected_fields(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=8,
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
        rid="SYS8",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    payload = render_requirements_docx(export, fields=["title", "statement"])

    with ZipFile(io.BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        assert "Important statement" in document_xml
        assert "Internal rationale" not in document_xml
        assert "Owner" not in document_xml


def test_render_requirements_docx_colorizes_labels_in_legend_and_cards(tmp_path: Path) -> None:
    doc = Document(
        prefix="SYS",
        title="System",
        labels=DocumentLabels(defs=[LabelDef("API", "API label", "#123456")]),
    )
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=9,
        title="Colorized",
        statement="Important statement",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="alice",
        priority=Priority.MEDIUM,
        source="spec",
        verification=Verification.ANALYSIS,
        attachments=[],
        labels=["API"],
        doc_prefix="SYS",
        rid="SYS9",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    payload = render_requirements_docx(export, colorize_label_backgrounds=True)

    with ZipFile(io.BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml").decode("utf-8")
        assert "API" in document_xml
        assert 'w:fill="123456"' in document_xml
        assert '<w:t xml:space="preserve"> API </w:t>' in document_xml


def test_render_requirements_docx_bolds_labels_field_caption_when_using_chips(tmp_path: Path) -> None:
    doc = Document(
        prefix="SYS",
        title="System",
        labels=DocumentLabels(defs=[LabelDef("api", "API", "#123456")]),
    )
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=11,
        title="Has labels",
        statement="Text",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="alice",
        priority=Priority.MEDIUM,
        source="spec",
        verification=Verification.ANALYSIS,
        labels=["API"],
        attachments=[],
        doc_prefix="SYS",
        rid="SYS11",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    payload = render_requirements_docx(
        export,
        fields=["labels"],
        colorize_label_backgrounds=True,
    )

    with ZipFile(io.BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml")

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    root = ET.fromstring(document_xml)

    labels_caption_bold: bool | None = None
    label_chip_bold: bool | None = None

    for run in root.findall('.//w:r', ns):
        text_value = ''.join(node.text or '' for node in run.findall('w:t', ns))
        if not text_value:
            continue
        has_bold = run.find('w:rPr/w:b', ns) is not None
        normalized = text_value.strip()
        if normalized == 'Labels:':
            labels_caption_bold = has_bold
        elif normalized == 'API':
            label_chip_bold = has_bold

    assert labels_caption_bold is True
    assert label_chip_bold is False


def test_render_requirements_docx_bolds_only_field_labels(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    save_document(doc_dir, doc)
    requirement = Requirement(
        id=10,
        title="Plain title",
        statement="Plain statement",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="alice",
        priority=Priority.MEDIUM,
        source="spec",
        verification=Verification.ANALYSIS,
        attachments=[],
        doc_prefix="SYS",
        rid="SYS10",
    )
    save_item(doc_dir, doc, requirement.to_mapping())

    export = build_requirement_export(tmp_path)
    payload = render_requirements_docx(export, fields=["title", "statement"])

    with ZipFile(io.BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml")

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    root = ET.fromstring(document_xml)

    title_label_bold: bool | None = None
    title_value_bold: bool | None = None
    statement_label_bold: bool | None = None
    statement_value_bold: bool | None = None

    for run in root.findall('.//w:r', ns):
        text_value = ''.join(node.text or '' for node in run.findall('w:t', ns))
        if not text_value:
            continue
        has_bold = run.find('w:rPr/w:b', ns) is not None
        if text_value == 'Title:':
            title_label_bold = has_bold
        elif text_value == 'Plain title':
            title_value_bold = has_bold
        elif text_value == 'Requirement text:':
            statement_label_bold = has_bold
        elif text_value == 'Plain statement':
            statement_value_bold = has_bold

    assert title_label_bold is True
    assert statement_label_bold is True
    assert title_value_bold is False
    assert statement_value_bold is False
