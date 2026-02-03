"""Utilities for exporting requirements into multiple formats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from io import BytesIO
from pathlib import Path
from collections.abc import Iterable, Mapping, Sequence
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, StyleSheet1, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from xml.sax.saxutils import escape as xml_escape

import markdown
import docx
from docx.shared import Inches

from .document_store import Document, DocumentNotFoundError, load_documents, load_requirements
from .markdown_utils import convert_markdown_math, sanitize_html, strip_markdown
from .model import Requirement

__all__ = [
    "DocumentExport",
    "RequirementExport",
    "RequirementExportLink",
    "RequirementExportView",
    "build_requirement_export",
    "build_requirement_export_from_requirements",
    "render_requirements_html",
    "render_requirements_markdown",
    "render_requirements_docx",
    "render_requirements_pdf",
]


SECTION_PLACEHOLDER = "(not provided)"
REQUIRED_SECTION_LABELS = {"Rationale"}


@dataclass(slots=True)
class RequirementExportLink:
    """Representation of a requirement relationship for export."""

    rid: str
    title: str | None
    exists: bool
    suspect: bool


@dataclass(slots=True)
class RequirementExportView:
    """View model combining requirement metadata and link summaries."""

    requirement: Requirement
    document: Document
    links: list[RequirementExportLink]


@dataclass(slots=True)
class DocumentExport:
    """Collection of requirements grouped by their document."""

    document: Document
    requirements: list[RequirementExportView]


@dataclass(slots=True)
class RequirementExport:
    """High-level container for exported data."""

    documents: list[DocumentExport]
    selected_prefixes: tuple[str, ...]
    generated_at: datetime
    base_path: Path


def _normalize_prefixes(prefixes: Sequence[str] | None, docs: Mapping[str, Document]) -> tuple[str, ...]:
    if prefixes is None:
        return tuple(sorted(docs))
    order: list[str] = []
    seen: set[str] = set()
    for prefix in prefixes:
        if prefix not in docs:
            raise DocumentNotFoundError(prefix)
        if prefix in seen:
            continue
        seen.add(prefix)
        order.append(prefix)
    return tuple(order)


def build_requirement_export(
    root: str | Path,
    *,
    prefixes: Sequence[str] | None = None,
) -> RequirementExport:
    """Load requirements and assemble a deterministic export representation."""
    root_path = Path(root)
    docs = load_documents(root_path)
    if not docs and not root_path.is_dir():
        raise FileNotFoundError(root_path)
    ordered_prefixes = _normalize_prefixes(prefixes, docs)
    requirements = load_requirements(root_path, prefixes=ordered_prefixes or None, docs=docs)
    by_rid = {req.rid: req for req in requirements}

    grouped: dict[str, DocumentExport] = {
        prefix: DocumentExport(document=docs[prefix], requirements=[])
        for prefix in ordered_prefixes
    }
    for req in requirements:
        export_doc = grouped[req.doc_prefix]
        links: list[RequirementExportLink] = []
        for link in req.links:
            target = by_rid.get(link.rid)
            links.append(
                RequirementExportLink(
                    rid=link.rid,
                    title=target.title if target else None,
                    exists=bool(target),
                    suspect=getattr(link, "suspect", False),
                )
            )
        export_doc.requirements.append(
            RequirementExportView(requirement=req, document=export_doc.document, links=links)
        )

    ordered_documents = [grouped[prefix] for prefix in ordered_prefixes]
    return RequirementExport(
        documents=ordered_documents,
        selected_prefixes=ordered_prefixes,
        generated_at=datetime.now(UTC),
        base_path=root_path,
    )


def build_requirement_export_from_requirements(
    requirements: Sequence[Requirement],
    docs: Mapping[str, Document],
    *,
    base_path: Path,
    prefixes: Sequence[str] | None = None,
    link_lookup: Sequence[Requirement] | None = None,
) -> RequirementExport:
    """Build export view model using preloaded requirements."""
    if prefixes is None:
        ordered_prefixes = tuple(sorted({req.doc_prefix for req in requirements}))
    else:
        ordered_prefixes = _normalize_prefixes(prefixes, docs)
    for prefix in ordered_prefixes:
        if prefix not in docs:
            raise DocumentNotFoundError(prefix)

    grouped: dict[str, DocumentExport] = {
        prefix: DocumentExport(document=docs[prefix], requirements=[])
        for prefix in ordered_prefixes
    }
    link_source = requirements if link_lookup is None else link_lookup
    by_rid = {req.rid: req for req in link_source}
    for req in requirements:
        if req.doc_prefix not in grouped:
            continue
        export_doc = grouped[req.doc_prefix]
        links: list[RequirementExportLink] = []
        for link in req.links:
            target = by_rid.get(link.rid)
            links.append(
                RequirementExportLink(
                    rid=link.rid,
                    title=target.title if target else None,
                    exists=bool(target),
                    suspect=getattr(link, "suspect", False),
                )
            )
        export_doc.requirements.append(
            RequirementExportView(requirement=req, document=export_doc.document, links=links)
        )

    ordered_documents = [grouped[prefix] for prefix in ordered_prefixes]
    return RequirementExport(
        documents=ordered_documents,
        selected_prefixes=ordered_prefixes,
        generated_at=datetime.now(UTC),
        base_path=base_path,
    )


def _format_markdown_block(text: str) -> list[str]:
    lines = text.splitlines() or [""]
    block: list[str] = []
    for line in lines:
        if line:
            block.append(f"> {line}")
        else:
            block.append(">")
    return block


def render_requirements_markdown(export: RequirementExport, *, title: str | None = None) -> str:
    """Render export data as Markdown."""
    heading = title or "Requirements export"
    parts: list[str] = [f"# {heading}", ""]
    parts.append(
        f"_Generated at {export.generated_at.isoformat()} for documents: {', '.join(export.selected_prefixes)}._"
    )
    parts.append("")

    for doc in export.documents:
        parts.append(f"## {doc.document.title} ({doc.document.prefix})")
        parts.append("")
        for view in doc.requirements:
            req = view.requirement
            parts.append(f"### {req.rid} — {req.title or '(no title)'}")
            parts.append("")
            parts.append(f"- **Type:** ``{req.type.value}``")
            parts.append(f"- **Status:** ``{req.status.value}``")
            if req.priority:
                parts.append(f"- **Priority:** ``{req.priority.value}``")
            if req.owner:
                parts.append(f"- **Owner:** {req.owner}")
            if req.labels:
                parts.append("- **Labels:** " + ", ".join(sorted(req.labels)))
            if req.source:
                parts.append(f"- **Source:** {req.source}")
            if req.modified_at:
                parts.append(f"- **Modified:** {req.modified_at}")
            if req.approved_at:
                parts.append(f"- **Approved:** {req.approved_at}")
            parts.append(f"- **Revision:** {req.revision}")
            parts.append("")

            sections: list[tuple[str, str | None, bool]] = [
                ("Statement", req.statement, False),
                ("Acceptance", req.acceptance or "", False),
                ("Conditions", req.conditions, False),
                ("Rationale", req.rationale, True),
                ("Assumptions", req.assumptions, False),
                ("Notes", req.notes, False),
            ]
            for label, value, required in sections:
                if not value and not required:
                    continue
                content = value if value else SECTION_PLACEHOLDER
                parts.append(f"**{label}**")
                parts.extend(_format_markdown_block(content))
                parts.append("")

            if view.links:
                parts.append("**Related requirements**")
                for link in view.links:
                    label = link.rid
                    if link.exists:
                        label = f"[{link.rid}](#{link.rid})"
                    suffix: list[str] = []
                    if link.title:
                        suffix.append(link.title)
                    if not link.exists:
                        suffix.append("missing")
                    if link.suspect:
                        suffix.append("suspect")
                    if suffix:
                        parts.append(f"- {label} — {', '.join(suffix)}")
                    else:
                        parts.append(f"- {label}")
                parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _escape_html(text: str) -> str:
    import html

    return html.escape(text)


_ATTACHMENT_LINK_RE = re.compile(r"!\[([^\]]*)\]\(attachment:([^)]+)\)")
_INLINE_FORMULA_RE = re.compile(r"\\\((.+?)\\\)")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$")


def _split_table_row(line: str) -> list[str]:
    raw = line.strip()
    if raw.startswith("|"):
        raw = raw[1:]
    if raw.endswith("|"):
        raw = raw[:-1]
    return [cell.strip() for cell in raw.split("|")]


def _latex_to_omml(latex: str) -> str | None:
    try:
        from latex2mathml.converter import convert as latex_to_mathml
        from mathml2omml import convert as mathml_to_omml
    except ImportError:
        return None
    try:
        mathml = latex_to_mathml(latex)
        return mathml_to_omml(mathml)
    except Exception:  # pragma: no cover - conversion failures
        return None


def _append_omml_run(paragraph: docx.text.paragraph.Paragraph, omml_xml: str) -> None:
    from docx.oxml import parse_xml

    if "xmlns:m=" not in omml_xml:
        if "<m:oMath" in omml_xml:
            omml_xml = omml_xml.replace(
                "<m:oMath",
                "<m:oMath xmlns:m=\"http://schemas.openxmlformats.org/officeDocument/2006/math\"",
                1,
            )
        else:
            omml_xml = (
                "<m:oMath xmlns:m=\"http://schemas.openxmlformats.org/officeDocument/2006/math\">"
                f"{omml_xml}</m:oMath>"
            )
    paragraph._p.append(parse_xml(omml_xml))


def _render_formula_run(
    paragraph: docx.text.paragraph.Paragraph,
    formula: str,
    *,
    formula_renderer: str,
) -> None:
    if formula_renderer == "mathml":
        omml = _latex_to_omml(formula)
        if omml:
            _append_omml_run(paragraph, omml)
            return
    if formula_renderer == "svg":
        image_bytes = _latex_to_svg_png(formula)
        if image_bytes:
            run = paragraph.add_run()
            run.add_picture(BytesIO(image_bytes))
            return
    if formula_renderer == "png":
        image_bytes = _latex_to_png(formula)
        if image_bytes:
            run = paragraph.add_run()
            run.add_picture(BytesIO(image_bytes))
            return
    paragraph.add_run(formula)


def _latex_to_png(latex: str) -> bytes | None:
    try:
        import matplotlib
        from matplotlib import pyplot as plt
    except ImportError:
        return None
    matplotlib.use("Agg", force=True)
    try:
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0.0, 0.0, f"${latex}$", fontsize=12)
        buffer = BytesIO()
        fig.savefig(
            buffer,
            format="png",
            bbox_inches="tight",
            pad_inches=0.1,
            transparent=True,
        )
        plt.close(fig)
        return buffer.getvalue()
    except Exception:  # pragma: no cover - rendering failures
        return None


def _latex_to_svg_png(latex: str) -> bytes | None:
    svg_bytes = _latex_to_svg(latex)
    if not svg_bytes:
        return None
    return _svg_to_png(svg_bytes)


def _latex_to_svg(latex: str) -> bytes | None:
    try:
        import matplotlib
        from matplotlib import pyplot as plt
    except ImportError:
        return None
    matplotlib.use("Agg", force=True)
    try:
        fig = plt.figure(figsize=(0.01, 0.01))
        fig.text(0.0, 0.0, f"${latex}$", fontsize=12)
        buffer = BytesIO()
        fig.savefig(
            buffer,
            format="svg",
            bbox_inches="tight",
            pad_inches=0.1,
            transparent=True,
        )
        plt.close(fig)
        return buffer.getvalue()
    except Exception:  # pragma: no cover - rendering failures
        return None


def _svg_to_png(svg_bytes: bytes) -> bytes | None:
    try:
        import cairosvg
    except ImportError:
        return None
    try:
        return cairosvg.svg2png(bytestring=svg_bytes)
    except Exception:  # pragma: no cover - rendering failures
        return None

def _build_markdown_renderer() -> markdown.Markdown:
    renderer = markdown.Markdown(
        extensions=[
            "markdown.extensions.tables",
            "markdown.extensions.fenced_code",
            "markdown.extensions.sane_lists",
        ],
        output_format="html5",
    )
    renderer.reset()
    return renderer


_MARKDOWN_RENDERER = _build_markdown_renderer()


def _render_markdown(text: str) -> str:
    renderer = _MARKDOWN_RENDERER
    renderer.reset()
    prepared = convert_markdown_math(text or "")
    markup = renderer.convert(prepared)
    return sanitize_html(markup)


def _attachment_markdown(text: str, *, requirement: Requirement) -> str:
    if "attachment:" not in text:
        return text
    attachment_map = {att.id: att.path for att in requirement.attachments}
    if not attachment_map:
        return text
    for attachment_id, path in attachment_map.items():
        text = text.replace(f"attachment:{attachment_id}", path)
    return text


def _html_markdown(value: str, *, requirement: Requirement) -> str:
    content = _attachment_markdown(value, requirement=requirement)
    return _render_markdown(content)


def render_requirements_html(export: RequirementExport, *, title: str | None = None) -> str:
    """Render export data as standalone HTML."""
    heading = title or "Requirements export"
    parts: list[str] = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>{_escape_html(heading)}</title>",
        "<style>html{font-size:16px;-webkit-text-size-adjust:100%;text-size-adjust:100%;}",
        "body{font-family:Arial,Helvetica,sans-serif;margin:24px;font-size:0.875rem;line-height:1.5;}",
        "h1{margin-top:0;font-size:1.5rem;}h2{font-size:1.25rem;}h3{font-size:1rem;}h4{font-size:0.875rem;margin-bottom:4px;}",
        "section.document{margin-bottom:32px;}",
        "article.requirement{border:1px solid #ddd;padding:16px;margin-bottom:16px;border-radius:8px;}",
        "article.requirement h3{margin-top:0;}article.requirement p{margin:0 0 8px;}",
        "dl.meta{display:grid;grid-template-columns:120px 1fr;gap:4px;margin:0 0 8px;}",
        "dl.meta dt{font-weight:bold;}dl.meta dd{margin:0;}ul.links{margin:8px 0 0 16px;}",
        "ul.links li{margin-bottom:4px;}span.missing{color:#b00020;}span.suspect{color:#a35a00;}",
        "</style>",
        "</head><body>",
        f"<h1>{_escape_html(heading)}</h1>",
        f"<p><em>Generated at {export.generated_at.isoformat()} for documents: {', '.join(export.selected_prefixes)}.</em></p>",
    ]

    for doc in export.documents:
        parts.append(f"<section class='document' id='doc-{_escape_html(doc.document.prefix)}'>")
        parts.append(
            f"<h2>{_escape_html(doc.document.title)} (<code>{_escape_html(doc.document.prefix)}</code>)</h2>"
        )
        for view in doc.requirements:
            req = view.requirement
            parts.append(f"<article class='requirement' id='{_escape_html(req.rid)}'>")
            parts.append(
                f"<h3><span class='rid'>{_escape_html(req.rid)}</span> — {_escape_html(req.title or '(no title)')}</h3>"
            )
            parts.append("<dl class='meta'>")
            meta_fields: Iterable[tuple[str, str | None]] = [
                ("Type", req.type.value),
                ("Status", req.status.value),
                ("Priority", getattr(req.priority, "value", None)),
                ("Owner", req.owner or None),
                ("Labels", ", ".join(sorted(req.labels)) if req.labels else None),
                ("Source", req.source or None),
                ("Modified", req.modified_at or None),
                ("Approved", req.approved_at or None),
                ("Revision", str(req.revision)),
            ]
            for label, value in meta_fields:
                if not value:
                    continue
                parts.append(f"<dt>{_escape_html(label)}</dt><dd>{_escape_html(value)}</dd>")
            parts.append("</dl>")

            for label, value in (
                ("Statement", req.statement),
                ("Acceptance", req.acceptance or ""),
                ("Conditions", req.conditions),
                ("Rationale", req.rationale),
                ("Assumptions", req.assumptions),
                ("Notes", req.notes),
            ):
                required = label in REQUIRED_SECTION_LABELS
                if not value and not required:
                    continue
                content = value if value else SECTION_PLACEHOLDER
                parts.append(f"<h4>{_escape_html(label)}</h4>")
                parts.append(_html_markdown(content, requirement=req) or "<p></p>")

            if view.links:
                parts.append("<h4>Related requirements</h4><ul class='links'>")
                for link in view.links:
                    label = _escape_html(link.rid)
                    title = _escape_html(link.title) if link.title else ""
                    classes: list[str] = []
                    if not link.exists:
                        classes.append("missing")
                    if link.suspect:
                        classes.append("suspect")
                    cls_attr = f" class='{' '.join(classes)}'" if classes else ""
                    if link.exists:
                        text = label if not title else f"{label} — {title}"
                        parts.append(
                            f"<li><a href='#{label}'{cls_attr}>{text}</a></li>"
                        )
                    else:
                        text_parts = [label]
                        if title:
                            text_parts.append(f"— {title}")
                        if not link.exists:
                            text_parts.append("(missing)")
                        if link.suspect:
                            text_parts.append("(suspect)")
                        parts.append(f"<li><span{cls_attr}>{' '.join(text_parts)}</span></li>")
                parts.append("</ul>")
            parts.append("</article>")
        parts.append("</section>")
    parts.append("</body></html>")
    return "".join(parts)


def _iter_markdown_segments(
    text: str,
    *,
    attachment_map: dict[str, str],
) -> list[tuple[str, str]]:
    if "attachment:" not in text:
        return [("text", text)]
    segments: list[tuple[str, str]] = []
    start = 0
    for match in _ATTACHMENT_LINK_RE.finditer(text):
        if match.start() > start:
            segments.append(("text", text[start:match.start()]))
        attachment_id = match.group(2).strip()
        path = attachment_map.get(attachment_id)
        if path:
            segments.append(("image", path))
        else:
            segments.append(("text", match.group(1)))
        start = match.end()
    if start < len(text):
        segments.append(("text", text[start:]))
    return segments


def _docx_add_markdown(
    doc: docx.Document,
    text: str,
    *,
    attachment_map: dict[str, str],
    base_path: Path,
    doc_prefix: str,
    image_width: float,
    formula_renderer: str,
) -> None:
    segments = _iter_markdown_segments(text, attachment_map=attachment_map)
    for kind, payload in segments:
        if kind == "image":
            image_path = base_path / doc_prefix / payload
            if image_path.exists():
                paragraph = doc.add_paragraph()
                run = paragraph.add_run()
                try:
                    run.add_picture(str(image_path), width=Inches(image_width))
                except (OSError, ValueError):  # pragma: no cover - invalid assets
                    doc.add_paragraph(strip_markdown(payload))
            else:
                doc.add_paragraph(strip_markdown(payload))
            continue
        lines = payload.splitlines()
        idx = 0
        while idx < len(lines):
            line = lines[idx]
            stripped = line.strip()
            if stripped.startswith("$$"):
                if stripped.endswith("$$") and len(stripped) > 4:
                    formula = stripped[2:-2].strip()
                    paragraph = doc.add_paragraph()
                    _render_formula_run(
                        paragraph,
                        formula,
                        formula_renderer=formula_renderer,
                    )
                    idx += 1
                    continue
                if stripped == "$$":
                    idx += 1
                    block_lines: list[str] = []
                    while idx < len(lines):
                        if lines[idx].strip() == "$$":
                            idx += 1
                            break
                        block_lines.append(lines[idx])
                        idx += 1
                    formula = "\n".join(block_lines).strip()
                    if formula:
                        paragraph = doc.add_paragraph()
                        _render_formula_run(
                            paragraph,
                            formula,
                            formula_renderer=formula_renderer,
                        )
                    continue
            if "|" in line and idx + 1 < len(lines) and _TABLE_SEPARATOR_RE.match(lines[idx + 1]):
                header_cells = _split_table_row(line)
                idx += 2
                table_rows: list[list[str]] = []
                while idx < len(lines):
                    row_line = lines[idx]
                    if "|" not in row_line:
                        break
                    row_cells = _split_table_row(row_line)
                    if row_cells:
                        table_rows.append(row_cells)
                    idx += 1
                if header_cells:
                    col_count = len(header_cells)
                    table = doc.add_table(rows=0, cols=col_count)
                    table.style = "Light Grid"
                    header_row = table.add_row().cells
                    for col_idx, cell in enumerate(header_cells):
                        header_row[col_idx].text = strip_markdown(cell)
                    for row in table_rows:
                        row_cells = table.add_row().cells
                        for col_idx, cell in enumerate(row[:col_count]):
                            row_cells[col_idx].text = strip_markdown(cell)
                continue
            if line.strip():
                paragraph = doc.add_paragraph()
                last_idx = 0
                for match in _INLINE_FORMULA_RE.finditer(line):
                    text_segment = line[last_idx:match.start()]
                    if text_segment:
                        paragraph.add_run(strip_markdown(text_segment))
                    formula = match.group(1).strip()
                    if formula:
                        _render_formula_run(
                            paragraph,
                            formula,
                            formula_renderer=formula_renderer,
                        )
                    last_idx = match.end()
                tail = line[last_idx:]
                if tail:
                    paragraph.add_run(strip_markdown(tail))
            else:
                doc.add_paragraph("")
            idx += 1


def render_requirements_docx(
    export: RequirementExport,
    *,
    title: str | None = None,
    formula_renderer: str = "text",
) -> bytes:
    """Render export data as a DOCX document."""
    heading = title or "Requirements export"
    document = docx.Document()
    document.add_heading(heading, level=0)
    document.add_paragraph(
        f"Generated at {export.generated_at.isoformat()} for documents: {', '.join(export.selected_prefixes)}."
    )
    image_width = 5.5

    for doc_export in export.documents:
        document.add_heading(
            f"{doc_export.document.title} ({doc_export.document.prefix})",
            level=1,
        )
        for view in doc_export.requirements:
            req = view.requirement
            document.add_heading(f"{req.rid} — {req.title or '(no title)'}", level=2)
            meta_fields: Iterable[tuple[str, str | None]] = [
                ("Type", req.type.value),
                ("Status", req.status.value),
                ("Priority", getattr(req.priority, "value", None)),
                ("Owner", req.owner or None),
                ("Labels", ", ".join(sorted(req.labels)) if req.labels else None),
                ("Source", req.source or None),
                ("Modified", req.modified_at or None),
                ("Approved", req.approved_at or None),
                ("Revision", str(req.revision)),
            ]
            meta_pairs = [(label, value) for label, value in meta_fields if value]
            if meta_pairs:
                table = document.add_table(rows=0, cols=2)
                table.style = "Light Grid"
                for label, value in meta_pairs:
                    row = table.add_row().cells
                    row[0].text = label
                    row[1].text = value

            attachment_map = {att.id: att.path for att in req.attachments}
            for label, value in (
                ("Statement", req.statement),
                ("Acceptance", req.acceptance or ""),
                ("Conditions", req.conditions),
                ("Rationale", req.rationale),
                ("Assumptions", req.assumptions),
                ("Notes", req.notes),
            ):
                required = label in REQUIRED_SECTION_LABELS
                if not value and not required:
                    continue
                content = value if value else SECTION_PLACEHOLDER
                document.add_heading(label, level=3)
                _docx_add_markdown(
                    document,
                    content,
                    attachment_map=attachment_map,
                    base_path=export.base_path,
                    doc_prefix=req.doc_prefix,
                    image_width=image_width,
                    formula_renderer=formula_renderer,
                )
            document.add_paragraph("")

    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _ensure_stylesheet() -> StyleSheet1:
    styles = getSampleStyleSheet()
    if "RequirementHeading" not in styles:
        styles.add(
            ParagraphStyle(
                "RequirementHeading",
                parent=styles["Heading3"],
                spaceBefore=12,
                spaceAfter=6,
            )
        )
    if "SectionHeading" not in styles:
        styles.add(
            ParagraphStyle(
                "SectionHeading",
                parent=styles["Heading4"],
                fontSize=11,
                leading=14,
                spaceBefore=6,
                spaceAfter=4,
            )
        )
    if "MetaValue" not in styles:
        styles.add(
            ParagraphStyle(
                "MetaValue",
                parent=styles["BodyText"],
                spaceBefore=0,
                spaceAfter=0,
            )
        )
    return styles


def _pdf_text(value: str) -> str:
    return xml_escape(value).replace("\n", "<br/>")


def render_requirements_pdf(export: RequirementExport, *, title: str | None = None) -> bytes:
    """Render export data as a PDF document."""
    buffer = BytesIO()
    heading = title or "Requirements export"
    styles = _ensure_stylesheet()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        title=heading,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )
    story: list = []
    story.append(Paragraph(xml_escape(heading), styles["Title"]))
    story.append(
        Paragraph(
            xml_escape(
                f"Generated at {export.generated_at.isoformat()} for documents: {', '.join(export.selected_prefixes)}."
            ),
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 12))

    for doc_export in export.documents:
        story.append(
            Paragraph(
                xml_escape(f"{doc_export.document.title} ({doc_export.document.prefix})"),
                styles["Heading2"],
            )
        )
        story.append(Spacer(1, 6))
        for view in doc_export.requirements:
            req = view.requirement
            story.append(
                Paragraph(
                    f"<a name='{xml_escape(req.rid)}'/><b>{xml_escape(req.rid)}</b> — {xml_escape(req.title or '(no title)')}",
                    styles["RequirementHeading"],
                )
            )
            data: list[list[str]] = []
            meta_fields: Iterable[tuple[str, str | None]] = [
                ("Type", req.type.value),
                ("Status", req.status.value),
                ("Priority", getattr(req.priority, "value", None)),
                ("Owner", req.owner or None),
                ("Labels", ", ".join(sorted(req.labels)) if req.labels else None),
                ("Source", req.source or None),
                ("Modified", req.modified_at or None),
                ("Approved", req.approved_at or None),
                ("Revision", str(req.revision)),
            ]
            for label, value in meta_fields:
                if not value:
                    continue
                data.append([xml_escape(label), _pdf_text(value)])
            if data:
                table = Table(data, colWidths=[40 * mm, 120 * mm])
                table.setStyle(
                    TableStyle(
                        [
                            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                            ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ]
                    )
                )
                story.append(table)
                story.append(Spacer(1, 6))

            for label, value in (
                ("Statement", req.statement),
                ("Acceptance", req.acceptance or ""),
                ("Conditions", req.conditions),
                ("Rationale", req.rationale),
                ("Assumptions", req.assumptions),
                ("Notes", req.notes),
            ):
                required = label in REQUIRED_SECTION_LABELS
                if not value and not required:
                    continue
                content = value if value else SECTION_PLACEHOLDER
                story.append(Paragraph(xml_escape(label), styles["SectionHeading"]))
                story.append(Paragraph(_pdf_text(content), styles["BodyText"]))

            if view.links:
                items = []
                for link in view.links:
                    label = xml_escape(link.rid)
                    if link.exists:
                        text = label
                        if link.title:
                            text += f" — {xml_escape(link.title)}"
                        if link.suspect:
                            text += " (suspect)"
                        items.append(
                            ListItem(
                                Paragraph(
                                    f"<link href='#{label}' color='blue'>{text}</link>",
                                    styles["BodyText"],
                                )
                            )
                        )
                    else:
                        text = label
                        if link.title:
                            text += f" — {xml_escape(link.title)}"
                        text += " (missing)"
                        if link.suspect:
                            text += " (suspect)"
                        items.append(ListItem(Paragraph(text, styles["BodyText"])))
                story.append(Paragraph("Related requirements", styles["SectionHeading"]))
                story.append(ListFlowable(items, bulletType="bullet"))
            story.append(Spacer(1, 12))
        story.append(Spacer(1, 12))

    doc.build(story)
    return buffer.getvalue()
