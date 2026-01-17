"""Command implementations for the CLI interface."""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from copy import deepcopy
from dataclasses import MISSING, asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, TextIO
from collections.abc import Callable, Mapping

from app.application import ApplicationContext
from app.confirm import confirm
from app.services.requirements import (
    RequirementsService,
    DocumentNotFoundError,
    RequirementIDCollisionError,
    RequirementNotFoundError,
    ValidationError,
    parse_rid,
)
from app.core.model import (
    Link,
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
    requirement_fingerprint,
)
from app.core.trace_matrix import (
    TraceDirection,
    TraceMatrix,
    TraceMatrixAxisConfig,
    TraceMatrixConfig,
    TraceMatrixLinkView,
    build_trace_matrix,
)
from app.core.requirement_export import (
    build_requirement_export,
    render_requirements_html,
    render_requirements_markdown,
    render_requirements_pdf,
)
from app.i18n import _

REQ_TYPE_CHOICES = [e.value for e in RequirementType]
STATUS_CHOICES = [e.value for e in Status]
PRIORITY_CHOICES = [e.value for e in Priority]
VERIFICATION_CHOICES = [e.value for e in Verification]

@dataclass
class Command:
    """Describe a CLI command and its argument handler."""

    func: Callable[[argparse.Namespace, ApplicationContext], None]
    help: str
    add_arguments: Callable[[argparse.ArgumentParser], None]


@dataclass
class ItemPayload:
    """Intermediate representation of arguments for ``cmd_item_add``."""

    title: str = ""
    statement: str = ""
    type: str = RequirementType.REQUIREMENT.value
    status: str = Status.DRAFT.value
    owner: str = ""
    priority: str = Priority.MEDIUM.value
    source: str = ""
    verification: str = Verification.ANALYSIS.value
    acceptance: str | None = None
    conditions: str = ""
    rationale: str = ""
    assumptions: str = ""
    modified_at: str = ""
    labels: list[str] = field(default_factory=list)
    attachments: list[Any] = field(default_factory=list)
    approved_at: str | None = None
    notes: str = ""
    links: list[str] = field(default_factory=list)
    revision: int | None = None

    def validate(self) -> None:
        """Ensure payload contains supported values."""
        errors: list[str] = []
        for field_name, enum_cls, message in (
            ("type", RequirementType, _("unknown requirement type: {value}")),
            ("status", Status, _("unknown status: {value}")),
            ("priority", Priority, _("unknown priority: {value}")),
            (
                "verification",
                Verification,
                _("unknown verification method: {value}"),
            ),
        ):
            value = getattr(self, field_name)
            try:
                enum_cls(value)
            except ValueError:
                errors.append(message.format(value=value))

        if not isinstance(self.labels, list):
            errors.append(_("labels must be a list"))
        if not isinstance(self.links, list):
            errors.append(_("links must be a list"))
        if not isinstance(self.attachments, list):
            errors.append(_("attachments must be a list"))
        if self.revision is not None and not isinstance(self.revision, int):
            errors.append(_("revision must be an integer"))

        if errors:
            raise ValidationError("; ".join(errors))

    def to_payload(self) -> dict[str, Any]:
        """Convert dataclass into dictionary suitable for persistence."""
        data = asdict(self)
        if self.revision is None:
            data.pop("revision", None)
        return data


def _default_for(field_def: Any) -> Any:
    if field_def.default is not MISSING:
        return field_def.default
    if field_def.default_factory is not MISSING:
        return field_def.default_factory()
    return None


def _split_csv(value: str) -> list[str]:
    return [token.strip() for token in value.split(",") if token.strip()]


def _flatten_arg_list(values: Any) -> list[str]:
    if values in (None, ""):
        return []
    if not isinstance(values, (list, tuple)):
        values = [values]
    tokens: list[str] = []
    for value in values:
        if value in (None, ""):
            continue
        if isinstance(value, str):
            tokens.extend(_split_csv(value))
        else:
            tokens.append(str(value))
    return tokens


def _load_template(data_arg: str | Path | None) -> dict[str, Any] | None:
    """Read optional JSON template referenced by ``--data`` arguments."""
    if not data_arg:
        return {}

    path = Path(data_arg)
    if not path.exists():
        sys.stdout.write(
            _("template file not found: {path}\n").format(path=path)
        )
        return None

    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        sys.stdout.write(
            _("invalid template JSON in {path}: {error}\n").format(
                path=path, error=str(exc)
            )
        )
        return None
    except OSError as exc:
        sys.stdout.write(
            _("failed to read template {path}: {error}\n").format(
                path=path, error=str(exc)
            )
        )
        return None

    if not isinstance(data, Mapping):
        sys.stdout.write(
            _("template must be a JSON object: {path}\n").format(path=path)
        )
        return None

    return dict(data)


def _service_for(
    context: ApplicationContext, directory: str | Path
) -> RequirementsService:
    """Return requirements service rooted at ``directory``."""
    factory = context.requirements_service_factory
    return factory(Path(directory))


def _build_axis_config(args: argparse.Namespace, axis: str) -> TraceMatrixAxisConfig:
    doc_attr = "rows" if axis == "row" else "columns"
    documents = tuple(_flatten_arg_list(getattr(args, doc_attr, [])))
    include_descendants = bool(
        getattr(args, f"{axis}_include_descendants", False)
    )
    statuses = tuple(_flatten_arg_list(getattr(args, f"{axis}_status", [])))
    requirement_types = tuple(
        _flatten_arg_list(getattr(args, f"{axis}_type", []))
    )
    labels_all = tuple(_flatten_arg_list(getattr(args, f"{axis}_label", [])))
    labels_any = tuple(
        _flatten_arg_list(getattr(args, f"{axis}_any_label", []))
    )
    query = str(getattr(args, f"{axis}_query", "") or "")
    query_fields = tuple(_flatten_arg_list(getattr(args, f"{axis}_fields", [])))
    return TraceMatrixAxisConfig(
        documents=documents,
        include_descendants=include_descendants,
        statuses=statuses,
        requirement_types=requirement_types,
        labels_all=labels_all,
        labels_any=labels_any,
        query=query,
        query_fields=query_fields,
    )


def _sorted_cell_links(matrix: TraceMatrix) -> list[TraceMatrixLinkView]:
    row_order = {entry.rid: index for index, entry in enumerate(matrix.rows)}
    column_order = {entry.rid: index for index, entry in enumerate(matrix.columns)}
    links: list[TraceMatrixLinkView] = []
    for _pair, cell in sorted(
        matrix.cells.items(),
        key=lambda pair_cell: (
            row_order.get(pair_cell[0][0], 10**9),
            column_order.get(pair_cell[0][1], 10**9),
        ),
    ):
        links.extend(cell.links)
    return links


def _write_trace_pairs(out: TextIO, matrix: TraceMatrix) -> None:
    for link in _sorted_cell_links(matrix):
        suffix = " !suspect" if link.suspect else ""
        out.write(f"{link.source_rid} {link.target_rid}{suffix}\n")


def _write_trace_matrix_csv(out: TextIO, matrix: TraceMatrix) -> None:
    writer = csv.writer(out)
    header = ["RID", "Title", "Document", "Status"]
    for column in matrix.columns:
        header.append(f"{column.rid} ({column.document.title})")
    writer.writerow(header)
    for row in matrix.rows:
        base = [
            row.rid,
            row.requirement.title,
            row.document.title,
            row.requirement.status.value,
        ]
        cells: list[str] = []
        for column in matrix.columns:
            cell = matrix.cells.get((row.rid, column.rid))
            if not cell or not cell.links:
                cells.append("")
            else:
                cells.append("suspect" if cell.suspect else "linked")
        writer.writerow(base + cells)


def _write_trace_matrix_html(out: TextIO, matrix: TraceMatrix) -> None:
    out.write(
        "<!DOCTYPE html>\n"
        "<html><head><meta charset='utf-8'>\n"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>\n"
    )
    out.write(
        "<style>"
        "html{font-size:16px;-webkit-text-size-adjust:100%;text-size-adjust:100%;}"
        "body{font-family:Arial,Helvetica,sans-serif;margin:24px;font-size:0.875rem;line-height:1.4;}"
        "table{border-collapse:collapse;font-size:inherit;}"
        "th,td{border:1px solid #ccc;padding:4px;text-align:left;font-size:inherit;}"
        "th{background:#f2f2f2;}"
        ".suspect{background:#fff3cd;} .linked{background:#d1f2d9;}"
        ".summary{margin-top:1em;} .summary dt{font-weight:bold;}"
        "</style>\n"
    )
    out.write("</head><body>\n<table>\n<thead><tr>")
    headers = ["RID", "Title", "Document", "Status"]
    for column in matrix.columns:
        headers.append(f"{column.rid} ({column.document.title})")
    for header in headers:
        out.write(f"<th>{html.escape(header)}</th>")
    out.write("</tr></thead>\n<tbody>\n")
    for row in matrix.rows:
        out.write("<tr>")
        out.write(f"<td>{html.escape(row.rid)}</td>")
        out.write(f"<td>{html.escape(row.requirement.title)}</td>")
        out.write(f"<td>{html.escape(row.document.title)}</td>")
        out.write(f"<td>{html.escape(row.requirement.status.value)}</td>")
        for column in matrix.columns:
            cell = matrix.cells.get((row.rid, column.rid))
            if not cell or not cell.links:
                out.write("<td></td>")
                continue
            cls = "suspect" if cell.suspect else "linked"
            label = "suspect" if cell.suspect else "linked"
            out.write(f"<td class='{cls}'>{html.escape(label)}</td>")
        out.write("</tr>\n")
    out.write("</tbody>\n</table>\n")
    summary = matrix.summary
    out.write("<dl class='summary'>\n")
    out.write(
        f"<dt>Total rows</dt><dd>{summary.total_rows}</dd>\n"
        f"<dt>Total columns</dt><dd>{summary.total_columns}</dd>\n"
        f"<dt>Linked pairs</dt><dd>{summary.linked_pairs} / {summary.total_pairs}</dd>\n"
        f"<dt>Links</dt><dd>{summary.link_count}</dd>\n"
        f"<dt>Row coverage</dt><dd>{summary.row_coverage:.2%}</dd>\n"
        f"<dt>Column coverage</dt><dd>{summary.column_coverage:.2%}</dd>\n"
        f"<dt>Pair coverage</dt><dd>{summary.pair_coverage:.2%}</dd>\n"
    )
    if summary.orphan_rows:
        orphan_rows = ", ".join(summary.orphan_rows)
        out.write(f"<dt>Rows without links</dt><dd>{html.escape(orphan_rows)}</dd>\n")
    if summary.orphan_columns:
        orphan_columns = ", ".join(summary.orphan_columns)
        out.write(
            f"<dt>Columns without links</dt><dd>{html.escape(orphan_columns)}</dd>\n"
        )
    out.write("</dl>\n</body></html>\n")


def _write_trace_matrix_json(out: TextIO, matrix: TraceMatrix) -> None:
    payload: dict[str, Any] = {
        "direction": matrix.direction.value,
        "rows": [
            {
                "rid": entry.rid,
                "title": entry.requirement.title,
                "status": entry.requirement.status.value,
                "type": entry.requirement.type.value,
                "labels": list(entry.requirement.labels),
                "document": {
                    "prefix": entry.document.prefix,
                    "title": entry.document.title,
                },
            }
            for entry in matrix.rows
        ],
        "columns": [
            {
                "rid": entry.rid,
                "title": entry.requirement.title,
                "status": entry.requirement.status.value,
                "type": entry.requirement.type.value,
                "labels": list(entry.requirement.labels),
                "document": {
                    "prefix": entry.document.prefix,
                    "title": entry.document.title,
                },
            }
            for entry in matrix.columns
        ],
        "cells": [
            {
                "row": row_rid,
                "column": column_rid,
                "links": [
                    {
                        "source": link.source_rid,
                        "target": link.target_rid,
                        "suspect": link.suspect,
                        "fingerprint": link.fingerprint,
                    }
                    for link in cell.links
                ],
            }
            for (row_rid, column_rid), cell in matrix.cells.items()
            if cell.links
        ],
        "summary": asdict(matrix.summary),
    }
    json.dump(payload, out, ensure_ascii=False, indent=2, sort_keys=True)
    out.write("\n")


def _resolve_text_field(
    args: argparse.Namespace,
    base: Mapping[str, Any],
    name: str,
    default: Any,
) -> Any:
    sentinel = object()
    arg_value = getattr(args, name, sentinel)
    if arg_value is not sentinel and arg_value not in (None, ""):
        return str(arg_value)
    base_value = base.get(name, sentinel)
    if base_value is not sentinel and base_value not in (None, ""):
        return base_value
    return default


def _resolve_optional_field(
    args: argparse.Namespace,
    base: Mapping[str, Any],
    name: str,
    default: Any,
) -> Any:
    sentinel = object()
    arg_value = getattr(args, name, sentinel)
    if arg_value is not sentinel:
        return arg_value
    return base.get(name, default)


def _resolve_labels(
    args: argparse.Namespace, base: Mapping[str, Any], default: list[str]
) -> list[str]:
    sentinel = object()
    arg_value = getattr(args, "labels", sentinel)
    if arg_value is not sentinel:
        if arg_value is None:
            return list(default)
        if isinstance(arg_value, str):
            return _split_csv(arg_value)
        if isinstance(arg_value, (list, tuple)):
            return [str(token) for token in arg_value if str(token).strip()]
    base_value = base.get("labels")
    if base_value is None:
        return list(default)
    if not isinstance(base_value, list):
        raise ValidationError(_("labels must be a list"))
    return [str(token) for token in base_value]


def _resolve_links(
    args: argparse.Namespace, base: Mapping[str, Any], default: list[str]
) -> list[str]:
    sentinel = object()
    arg_value = getattr(args, "links", sentinel)
    if arg_value not in (sentinel, None, ""):
        if isinstance(arg_value, str):
            return _split_csv(arg_value)
        if isinstance(arg_value, (list, tuple)):
            return [str(token) for token in arg_value if str(token).strip()]
    base_value = base.get("links")
    if base_value is None:
        return list(default)
    if not isinstance(base_value, list):
        raise ValidationError(_("links must be a list"))
    resolved: list[str] = []
    for entry in base_value:
        if isinstance(entry, str):
            token = entry.strip()
            if token:
                resolved.append(token)
            continue
        if isinstance(entry, Mapping):
            rid = entry.get("rid")
            if isinstance(rid, str) and rid.strip():
                resolved.append(rid.strip())
            continue
        raise ValidationError(_("links must be a list"))
    return resolved


def _resolve_attachments(
    args: argparse.Namespace, base: Mapping[str, Any], default: list[Any]
) -> list[Any]:
    sentinel = object()
    arg_value = getattr(args, "attachments", sentinel)
    if arg_value not in (sentinel, None, ""):
        parsed = json.loads(arg_value)
        return parsed
    base_value = base.get("attachments")
    if base_value is None:
        return list(default)
    if not isinstance(base_value, list):
        raise ValidationError(_("attachments must be a list"))
    return deepcopy(base_value)


def _resolve_revision(
    args: argparse.Namespace, base: Mapping[str, Any]
) -> int | None:
    sentinel = object()
    arg_value = getattr(args, "revision", sentinel)
    value = arg_value
    if arg_value is sentinel or arg_value is None:
        value = base.get("revision")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ValidationError(_("revision must be an integer")) from exc


def build_item_payload(
    args: argparse.Namespace, base: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Combine CLI arguments and base data into payload for creation."""
    base_data: Mapping[str, Any] = base or {}
    values: dict[str, Any] = {}
    for field_def in fields(ItemPayload):
        default = _default_for(field_def)
        if field_def.name == "labels":
            values[field_def.name] = _resolve_labels(args, base_data, default)
        elif field_def.name == "links":
            values[field_def.name] = _resolve_links(args, base_data, default)
        elif field_def.name == "attachments":
            values[field_def.name] = _resolve_attachments(args, base_data, default)
        elif field_def.name in {"acceptance", "approved_at"}:
            values[field_def.name] = _resolve_optional_field(
                args, base_data, field_def.name, default
            )
        elif field_def.name == "revision":
            values[field_def.name] = _resolve_revision(args, base_data)
        else:
            values[field_def.name] = _resolve_text_field(
                args, base_data, field_def.name, default
            )
    payload = ItemPayload(**values)
    payload.validate()
    return payload.to_payload()


def cmd_doc_create(
    args: argparse.Namespace, context: ApplicationContext
) -> None:
    """Create new document within requirements root."""
    service = _service_for(context, args.directory)
    doc = service.create_document(
        prefix=args.prefix,
        title=args.title,
        parent=args.parent,
    )
    sys.stdout.write(f"{doc.prefix}\n")


def cmd_doc_list(
    args: argparse.Namespace, context: ApplicationContext
) -> None:
    """List documents configured under requirements root."""
    service = _service_for(context, args.directory)
    docs = service.load_documents(refresh=True)
    for prefix in sorted(docs):
        doc = docs[prefix]
        sys.stdout.write(f"{doc.prefix} {doc.title}\n")


def cmd_doc_delete(
    args: argparse.Namespace, context: ApplicationContext
) -> None:
    """Delete document ``prefix`` and its descendants."""
    service = _service_for(context, args.directory)
    if getattr(args, "dry_run", False):
        doc_list, item_list = service.plan_delete_document(args.prefix)
        if not doc_list:
            sys.stdout.write(
                _("document not found: {prefix}\n").format(prefix=args.prefix)
            )
            return
        for p in doc_list:
            sys.stdout.write(f"{p}\n")
        for rid in item_list:
            sys.stdout.write(f"{rid}\n")
        return
    msg = _("Delete document {prefix} and its subtree?").format(prefix=args.prefix)
    if not confirm(msg):
        sys.stdout.write(_("aborted\n"))
        return
    removed = service.delete_document(args.prefix)
    if removed:
        sys.stdout.write(f"{args.prefix}\n")
    else:
        sys.stdout.write(
            _("document not found: {prefix}\n").format(prefix=args.prefix)
        )


def add_doc_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for ``doc`` subcommands."""
    sub = p.add_subparsers(dest="doc_command", required=True)

    create = sub.add_parser("create", help=_("create document"))
    create.add_argument("directory", help=_("requirements root"))
    create.add_argument("prefix", help=_("document prefix"))
    create.add_argument("title", help=_("document title"))
    create.add_argument("--parent", help=_("parent document prefix"))
    create.set_defaults(func=cmd_doc_create)

    lst = sub.add_parser("list", help=_("list documents"))
    lst.add_argument("directory", help=_("requirements root"))
    lst.set_defaults(func=cmd_doc_list)

    del_p = sub.add_parser("delete", help=_("delete document"))
    del_p.add_argument("directory", help=_("requirements root"))
    del_p.add_argument("prefix", help=_("document prefix"))
    del_p.add_argument(
        "--dry-run",
        action="store_true",
        help=_("show what would be deleted"),
    )
    del_p.set_defaults(func=cmd_doc_delete)


def cmd_item_add(
    args: argparse.Namespace, context: ApplicationContext
) -> None:
    """Create a new requirement item under a document."""
    base = _load_template(getattr(args, "data", None))
    if base is None:
        return
    service = _service_for(context, args.directory)
    try:
        payload = build_item_payload(args, base)
        req = service.create_requirement(prefix=args.prefix, data=payload)
    except DocumentNotFoundError:
        sys.stdout.write(
            _("unknown document prefix: {prefix}\n").format(prefix=args.prefix)
        )
        return
    except ValidationError as exc:
        sys.stdout.write(_("{msg}\n").format(msg=str(exc)))
        return
    sys.stdout.write(f"{req.rid}\n")


def cmd_item_edit(
    args: argparse.Namespace, context: ApplicationContext
) -> None:
    """Update an existing requirement without changing its RID."""
    prefix, item_id = parse_rid(args.rid)
    service = _service_for(context, args.directory)
    try:
        doc = service.get_document(prefix)
    except DocumentNotFoundError:
        sys.stdout.write(_("document not found: {prefix}\n").format(prefix=prefix))
        return
    try:
        data, _mtime = service.load_item(prefix, item_id)
    except FileNotFoundError:
        sys.stdout.write(_("item not found: {rid}\n").format(rid=args.rid))
        return

    template = _load_template(getattr(args, "data", None))
    if template is None:
        return

    base_payload: dict[str, Any] = dict(data)
    base_payload.update(template)

    try:
        payload = build_item_payload(args, base_payload)
    except ValidationError as exc:
        sys.stdout.write(_("{msg}\n").format(msg=str(exc)))
        return

    labels = list(payload.get("labels", []))
    err = service.validate_labels(prefix, labels)
    if err:
        sys.stdout.write(_("{msg}\n").format(msg=err))
        return
    payload["labels"] = labels

    payload["id"] = int(data["id"])

    req = Requirement.from_mapping(payload, doc_prefix=doc.prefix, rid=args.rid)
    service.save_requirement_payload(prefix, req.to_mapping())
    sys.stdout.write(f"{req.rid}\n")


def cmd_item_move(
    args: argparse.Namespace, context: ApplicationContext
) -> None:
    """Move existing item ``rid`` to document ``new_prefix``."""
    service = _service_for(context, args.directory)
    try:
        current = service.get_requirement(args.rid)
    except RequirementNotFoundError:
        sys.stdout.write(_("requirement not found: {rid}\n").format(rid=args.rid))
        return

    template = _load_template(getattr(args, "data", None))
    if template is None:
        return

    base_payload: dict[str, Any] = current.to_mapping()
    base_payload.update(template)

    try:
        payload = build_item_payload(args, base_payload)
    except ValidationError as exc:
        sys.stdout.write(_("{msg}\n").format(msg=str(exc)))
        return

    try:
        moved = service.move_requirement(
            args.rid,
            new_prefix=args.new_prefix,
            payload=payload,
        )
    except DocumentNotFoundError:
        sys.stdout.write(
            _("unknown document prefix: {prefix}\n").format(prefix=args.new_prefix)
        )
        return
    except RequirementNotFoundError:
        sys.stdout.write(_("requirement not found: {rid}\n").format(rid=args.rid))
        return
    except RequirementIDCollisionError as exc:
        sys.stdout.write(_("{msg}\n").format(msg=str(exc)))
        return
    except ValidationError as exc:
        sys.stdout.write(_("{msg}\n").format(msg=str(exc)))
        return

    sys.stdout.write(f"{moved.rid}\n")


def cmd_item_delete(
    args: argparse.Namespace, context: ApplicationContext
) -> None:
    """Delete requirement ``rid`` and update references."""
    service = _service_for(context, args.directory)
    if getattr(args, "dry_run", False):
        exists, refs = service.plan_delete_requirement(args.rid)
        if not exists:
            sys.stdout.write(_("item not found: {rid}\n").format(rid=args.rid))
            return
        sys.stdout.write(f"{args.rid}\n")
        for r in refs:
            sys.stdout.write(f"{r}\n")
        return
    msg = _("Delete item {rid}?").format(rid=args.rid)
    if not confirm(msg):
        sys.stdout.write(_("aborted\n"))
        return
    try:
        canonical = service.delete_requirement(args.rid)
    except ValueError as exc:
        sys.stdout.write(_("{msg}\n").format(msg=str(exc)))
        return
    except ValidationError as exc:
        sys.stdout.write(
            _("cannot delete {rid}: revision error: {msg}\n").format(
                rid=args.rid, msg=str(exc)
            )
        )
        return
    except RequirementNotFoundError:
        sys.stdout.write(_("item not found: {rid}\n").format(rid=args.rid))
        return
    sys.stdout.write(f"{canonical}\n")


def _add_item_payload_arguments(parser: argparse.ArgumentParser) -> None:
    """Add common requirement field arguments to ``parser``."""
    parser.add_argument("--title", help=_("item title"))
    parser.add_argument("--statement", help=_("item statement"))
    parser.add_argument(
        "--type",
        choices=REQ_TYPE_CHOICES,
        default=RequirementType.REQUIREMENT.value,
    )
    parser.add_argument(
        "--status", choices=STATUS_CHOICES, default=Status.DRAFT.value
    )
    parser.add_argument("--owner", default="")
    parser.add_argument(
        "--priority", choices=PRIORITY_CHOICES, default=Priority.MEDIUM.value
    )
    parser.add_argument("--source", default="")
    parser.add_argument(
        "--verification",
        choices=VERIFICATION_CHOICES,
        default=Verification.ANALYSIS.value,
    )
    parser.add_argument("--acceptance")
    parser.add_argument("--conditions")
    parser.add_argument("--rationale")
    parser.add_argument("--assumptions")
    parser.add_argument("--modified-at", dest="modified_at")
    parser.add_argument("--approved-at", dest="approved_at")
    parser.add_argument("--notes")
    parser.add_argument("--attachments", help=_("JSON list of attachments"))
    parser.add_argument(
        "--labels", dest="labels", help=_("comma-separated labels")
    )
    parser.add_argument(
        "--links", help=_("comma-separated parent requirement IDs")
    )
    parser.add_argument("--data", help=_("JSON template file"))


def add_item_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for ``item`` subcommands."""
    sub = p.add_subparsers(dest="item_command", required=True)

    add_p = sub.add_parser("add", help=_("create new item"))
    add_p.add_argument("directory", help=_("requirements root"))
    add_p.add_argument("prefix", help=_("document prefix"))
    _add_item_payload_arguments(add_p)
    add_p.set_defaults(func=cmd_item_add)

    edit_p = sub.add_parser("edit", help=_("edit existing item"))
    edit_p.add_argument("directory", help=_("requirements root"))
    edit_p.add_argument("rid", help=_("requirement identifier"))
    _add_item_payload_arguments(edit_p)
    edit_p.set_defaults(func=cmd_item_edit)

    move_p = sub.add_parser("move", help=_("move item"))
    move_p.add_argument("directory", help=_("requirements root"))
    move_p.add_argument("rid", help=_("requirement identifier"))
    move_p.add_argument("new_prefix", help=_("target document prefix"))
    move_p.add_argument("--title")
    move_p.add_argument("--statement")
    move_p.add_argument("--type", choices=REQ_TYPE_CHOICES)
    move_p.add_argument("--status", choices=STATUS_CHOICES)
    move_p.add_argument("--owner")
    move_p.add_argument("--priority", choices=PRIORITY_CHOICES)
    move_p.add_argument("--source")
    move_p.add_argument("--verification", choices=VERIFICATION_CHOICES)
    move_p.add_argument("--acceptance")
    move_p.add_argument("--conditions")
    move_p.add_argument("--rationale")
    move_p.add_argument("--assumptions")
    move_p.add_argument("--modified-at", dest="modified_at")
    move_p.add_argument("--approved-at", dest="approved_at")
    move_p.add_argument("--notes")
    move_p.add_argument("--attachments", help=_("JSON list of attachments"))
    move_p.add_argument("--labels", dest="labels", help=_("comma-separated labels"))
    move_p.add_argument("--links", help=_("comma-separated parent requirement IDs"))
    move_p.add_argument("--data", help=_("JSON template file"))
    move_p.set_defaults(func=cmd_item_move)

    del_p = sub.add_parser("delete", help=_("delete item"))
    del_p.add_argument("directory", help=_("requirements root"))
    del_p.add_argument("rid", help=_("requirement identifier"))
    del_p.add_argument(
        "--dry-run",
        action="store_true",
        help=_("show what would be deleted"),
    )
    del_p.set_defaults(func=cmd_item_delete)


def cmd_link(
    args: argparse.Namespace, context: ApplicationContext
) -> None:
    """Add links from requirement ``rid`` to ``parents``."""
    service = _service_for(context, args.directory)
    try:
        prefix, item_id = parse_rid(args.rid)
    except ValueError:
        sys.stdout.write(_("invalid requirement identifier: {rid}\n").format(rid=args.rid))
        return
    try:
        doc = service.get_document(prefix)
    except DocumentNotFoundError:
        sys.stdout.write(_("unknown document prefix: {prefix}\n").format(prefix=prefix))
        return
    try:
        data, _mtime = service.load_item(prefix, item_id)
    except FileNotFoundError:
        sys.stdout.write(_("item not found: {rid}\n").format(rid=args.rid))
        return
    parent_payloads: dict[str, dict] = {}
    for rid in args.parents:
        if rid == args.rid:
            sys.stdout.write(_("invalid link target: {rid}\n").format(rid=rid))
            return
        try:
            parent_prefix, parent_id = parse_rid(rid)
        except ValueError:
            sys.stdout.write(_("invalid requirement identifier: {rid}\n").format(rid=rid))
            return
        try:
            service.get_document(parent_prefix)
        except DocumentNotFoundError:
            sys.stdout.write(_("unknown document prefix: {prefix}\n").format(prefix=parent_prefix))
            return
        if not service.is_ancestor(prefix, parent_prefix):
            sys.stdout.write(_("invalid link target: {rid}\n").format(rid=rid))
            return
        try:
            parent_data, _parent_mtime = service.load_item(parent_prefix, parent_id)
        except FileNotFoundError:
            sys.stdout.write(_("linked item not found: {rid}\n").format(rid=rid))
            return
        parent_payloads[rid] = parent_data

    req = Requirement.from_mapping(data, doc_prefix=doc.prefix, rid=args.rid)
    existing_links = {link.rid: link for link in getattr(req, "links", [])}
    if args.replace:
        existing_links.clear()
    for rid, parent_data in parent_payloads.items():
        existing_links[rid] = Link(
            rid=rid,
            fingerprint=requirement_fingerprint(parent_data),
            suspect=False,
        )
    req.links = [existing_links[rid] for rid in sorted(existing_links)]
    service.save_requirement_payload(prefix, req.to_mapping())
    sys.stdout.write(f"{args.rid}\n")


def add_link_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for the ``link`` command."""
    p.add_argument("directory", help=_("requirements root"))
    p.add_argument("rid", help=_("requirement identifier"))
    p.add_argument("parents", nargs="+", help=_("parent requirement identifiers"))
    p.add_argument(
        "--replace",
        action="store_true",
        help=_("replace existing links instead of adding"),
    )


def _open_trace_output(path: str | None) -> tuple[TextIO, bool]:
    if not path:
        return sys.stdout, False
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return out_path.open("w", encoding="utf-8", newline=""), True


def _open_export_output(path: str | None, *, binary: bool) -> tuple[Any, bool]:
    if not path:
        return (sys.stdout.buffer if binary else sys.stdout), False
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        return out_path.open("wb"), True
    return out_path.open("w", encoding="utf-8"), True


def cmd_trace(
    args: argparse.Namespace, context: ApplicationContext
) -> None:
    """Export traceability matrix in the requested format."""
    row_axis = _build_axis_config(args, "row")
    column_axis = _build_axis_config(args, "column")

    if not row_axis.documents:
        raise SystemExit(_("at least one --rows value is required"))
    if not column_axis.documents:
        raise SystemExit(_("at least one --columns value is required"))

    direction_raw = getattr(args, "direction", TraceDirection.CHILD_TO_PARENT.value)
    try:
        direction = TraceDirection(direction_raw)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    config = TraceMatrixConfig(rows=row_axis, columns=column_axis, direction=direction)

    try:
        matrix = build_trace_matrix(args.directory, config)
    except (DocumentNotFoundError, FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc

    fmt = getattr(args, "format", "pairs")
    out, close_out = _open_trace_output(getattr(args, "output", None))
    try:
        if fmt == "pairs":
            _write_trace_pairs(out, matrix)
        elif fmt == "matrix-csv":
            _write_trace_matrix_csv(out, matrix)
        elif fmt == "matrix-html":
            _write_trace_matrix_html(out, matrix)
        elif fmt == "matrix-json":
            _write_trace_matrix_json(out, matrix)
        else:  # pragma: no cover - defensive
            raise SystemExit(f"unknown format: {fmt}")
    finally:
        if close_out:
            out.close()


def cmd_export_requirements(
    args: argparse.Namespace, context: ApplicationContext
) -> None:
    """Export requirements into Markdown, HTML, or PDF."""
    selected_docs = tuple(_flatten_arg_list(getattr(args, "documents", []))) or None

    try:
        export = build_requirement_export(args.directory, prefixes=selected_docs)
    except (DocumentNotFoundError, FileNotFoundError) as exc:
        raise SystemExit(str(exc)) from exc

    title = getattr(args, "title", None) or _("Requirements export")
    fmt = getattr(args, "format", "markdown")

    if fmt == "markdown":
        payload = render_requirements_markdown(export, title=title)
        out, close_out = _open_export_output(getattr(args, "output", None), binary=False)
        try:
            out.write(payload)
        finally:
            if close_out:
                out.close()
        return

    if fmt == "html":
        payload = render_requirements_html(export, title=title)
        out, close_out = _open_export_output(getattr(args, "output", None), binary=False)
        try:
            out.write(payload)
        finally:
            if close_out:
                out.close()
        return

    if fmt == "pdf":
        payload = render_requirements_pdf(export, title=title)
        out, close_out = _open_export_output(getattr(args, "output", None), binary=True)
        try:
            out.write(payload)
        finally:
            if close_out:
                out.close()
        return

    raise SystemExit(f"unknown format: {fmt}")


def add_export_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for the ``export`` command."""
    sub = p.add_subparsers(dest="export_command", required=True)

    req = sub.add_parser("requirements", help=_("export requirements"))
    req.add_argument("directory", help=_("requirements root"))
    req.add_argument(
        "-d",
        "--documents",
        "--doc",
        dest="documents",
        action="append",
        default=[],
        help=_("document prefixes (comma separated)"),
    )
    req.add_argument(
        "--format",
        choices=["markdown", "html", "pdf"],
        default="markdown",
        help=_("output format"),
    )
    req.add_argument("-o", "--output", help=_("write result to file"))
    req.add_argument("--title", help=_("title for exported document"))
    req.set_defaults(func=cmd_export_requirements)


def add_trace_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for the ``trace`` command."""
    p.add_argument("directory", help=_("requirements root"))
    p.add_argument(
        "-r",
        "--rows",
        action="append",
        default=[],
        help=_("row document prefixes (comma separated)"),
    )
    p.add_argument(
        "-c",
        "--columns",
        "--cols",
        dest="columns",
        action="append",
        default=[],
        help=_("column document prefixes (comma separated)"),
    )
    p.add_argument(
        "--row-include-descendants",
        action="store_true",
        help=_("include descendant documents for rows"),
    )
    p.add_argument(
        "--column-include-descendants",
        action="store_true",
        help=_("include descendant documents for columns"),
    )
    p.add_argument(
        "--row-status",
        action="append",
        default=[],
        help=_("filter rows by status"),
    )
    p.add_argument(
        "--column-status",
        action="append",
        default=[],
        help=_("filter columns by status"),
    )
    p.add_argument(
        "--row-type",
        action="append",
        default=[],
        help=_("filter rows by requirement type"),
    )
    p.add_argument(
        "--column-type",
        action="append",
        default=[],
        help=_("filter columns by requirement type"),
    )
    p.add_argument(
        "--row-label",
        action="append",
        default=[],
        help=_("require all labels on rows"),
    )
    p.add_argument(
        "--column-label",
        action="append",
        default=[],
        help=_("require all labels on columns"),
    )
    p.add_argument(
        "--row-any-label",
        action="append",
        default=[],
        help=_("keep rows with any of the labels"),
    )
    p.add_argument(
        "--column-any-label",
        action="append",
        default=[],
        help=_("keep columns with any of the labels"),
    )
    p.add_argument("--row-query", help=_("text query for rows"))
    p.add_argument("--column-query", help=_("text query for columns"))
    p.add_argument(
        "--row-fields",
        action="append",
        default=[],
        help=_("limit row search fields (comma separated)"),
    )
    p.add_argument(
        "--column-fields",
        action="append",
        default=[],
        help=_("limit column search fields (comma separated)"),
    )
    p.add_argument(
        "--format",
        choices=["pairs", "matrix-csv", "matrix-html", "matrix-json"],
        default="pairs",
        help=_("output format"),
    )
    p.add_argument(
        "--direction",
        choices=[choice.value for choice in TraceDirection],
        default=TraceDirection.CHILD_TO_PARENT.value,
        help=_("interpretation of links"),
    )
    p.add_argument("-o", "--output", help=_("write result to file"))


def cmd_check(
    args: argparse.Namespace, context: ApplicationContext
) -> None:
    """Verify LLM and MCP connectivity using loaded settings."""
    agent = context.local_agent_factory(
        args.app_settings,
        confirm_override=confirm,
    )
    results: dict[str, object] = {}
    if args.llm or not (args.llm or args.mcp):
        results["llm"] = agent.check_llm()
    if args.mcp or not (args.llm or args.mcp):
        results["mcp"] = agent.check_tools()
    sys.stdout.write(
        json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def add_check_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for the ``check`` command."""
    p.add_argument("--llm", action="store_true", help=_("check only LLM"))
    p.add_argument("--mcp", action="store_true", help=_("check only MCP"))


COMMANDS: dict[str, Command] = {
    "doc": Command(
        lambda args, context: args.func(args, context),
        _("manage documents"),
        add_doc_arguments,
    ),
    "item": Command(
        lambda args, context: args.func(args, context),
        _("manage items"),
        add_item_arguments,
    ),
    "link": Command(cmd_link, _("link requirements"), add_link_arguments),
    "trace": Command(cmd_trace, _("export trace links"), add_trace_arguments),
    "export": Command(
        lambda args, context: args.func(args, context),
        _("export data"),
        add_export_arguments,
    ),
    "check": Command(cmd_check, _("verify LLM and MCP settings"), add_check_arguments),
}
