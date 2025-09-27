"""Utilities for exporting requirements into multiple formats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Iterable, Mapping, Sequence

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

from .document_store import Document, DocumentNotFoundError, load_documents, load_requirements
from .model import Requirement

__all__ = [
    "DocumentExport",
    "RequirementExport",
    "RequirementExportLink",
    "RequirementExportView",
    "build_requirement_export",
    "render_requirements_html",
    "render_requirements_markdown",
    "render_requirements_pdf",
]


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
    if not docs:
        if not root_path.is_dir():
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
        generated_at=datetime.now(timezone.utc),
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
            parts.append("- **Type:** ``{}``".format(req.type.value))
            parts.append("- **Status:** ``{}``".format(req.status.value))
            if req.priority:
                parts.append("- **Priority:** ``{}``".format(req.priority.value))
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
            parts.append("- **Revision:** {}".format(req.revision))
            parts.append("")

            sections: list[tuple[str, str | None]] = [
                ("Statement", req.statement),
                ("Acceptance", req.acceptance or ""),
                ("Conditions", req.conditions),
                ("Rationale", req.rationale),
                ("Assumptions", req.assumptions),
                ("Notes", req.notes),
            ]
            for label, value in sections:
                if not value:
                    continue
                parts.append(f"**{label}**")
                parts.extend(_format_markdown_block(value))
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


def _html_paragraphs(value: str) -> str:
    paragraphs = []
    for raw in value.split("\n\n"):
        raw = raw.strip()
        if not raw:
            continue
        lines = [_escape_html(line) for line in raw.splitlines()]
        paragraphs.append("<p>" + "<br>".join(lines) + "</p>")
    return "".join(paragraphs)


def render_requirements_html(export: RequirementExport, *, title: str | None = None) -> str:
    """Render export data as standalone HTML."""

    heading = title or "Requirements export"
    parts: list[str] = [
        "<!DOCTYPE html>",
        "<html><head><meta charset='utf-8'>",
        f"<title>{_escape_html(heading)}</title>",
        "<style>body{font-family:Arial,Helvetica,sans-serif;margin:24px;}",
        "h1{margin-top:0;}section.document{margin-bottom:32px;}",
        "article.requirement{border:1px solid #ddd;padding:16px;margin-bottom:16px;border-radius:8px;}",
        "article.requirement h3{margin-top:0;}dl.meta{display:grid;grid-template-columns:120px 1fr;gap:4px;}",
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
                if not value:
                    continue
                parts.append(f"<h4>{_escape_html(label)}</h4>")
                parts.append(_html_paragraphs(value) or "<p></p>")

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
                if not value:
                    continue
                story.append(Paragraph(xml_escape(label), styles["SectionHeading"]))
                story.append(Paragraph(_pdf_text(value), styles["BodyText"]))

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

