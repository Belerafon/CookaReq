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
from typing import Any, Callable, Mapping, TextIO

from app.confirm import confirm
from app.core.document_store import (
    Document,
    DocumentNotFoundError,
    ValidationError,
    create_requirement,
    delete_document,
    delete_item,
    is_ancestor,
    iter_links,
    item_path,
    load_document,
    load_documents,
    load_item,
    locate_item_path,
    next_item_id,
    parse_rid,
    plan_delete_document,
    plan_delete_item,
    rid_for,
    save_document,
    save_item,
    validate_labels,
)
from app.core.model import (
    Priority,
    RequirementType,
    Status,
    Verification,
    requirement_from_dict,
    requirement_to_dict,
)
from app.i18n import _

REQ_TYPE_CHOICES = [e.value for e in RequirementType]
STATUS_CHOICES = [e.value for e in Status]
PRIORITY_CHOICES = [e.value for e in Priority]
VERIFICATION_CHOICES = [e.value for e in Verification]


@dataclass
class Command:
    """Describe a CLI command and its argument handler."""

    func: Callable[[argparse.Namespace], None]
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
    return [str(token) for token in base_value]


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


def cmd_doc_create(args: argparse.Namespace) -> None:
    """Create new document within requirements root."""

    doc = Document(
        prefix=args.prefix,
        title=args.title,
        digits=args.digits,
        parent=args.parent,
    )
    save_document(Path(args.directory) / args.prefix, doc)
    sys.stdout.write(f"{args.prefix}\n")


def cmd_doc_list(args: argparse.Namespace) -> None:
    """List documents configured under requirements root."""

    root = Path(args.directory)
    for path in sorted(root.iterdir()):
        if (path / "document.json").is_file():
            doc = load_document(path)
            sys.stdout.write(f"{doc.prefix} {doc.title}\n")


def cmd_doc_delete(args: argparse.Namespace) -> None:
    """Delete document ``prefix`` and its descendants."""

    docs = load_documents(args.directory)
    if getattr(args, "dry_run", False):
        doc_list, item_list = plan_delete_document(
            args.directory, args.prefix, docs
        )
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
    removed = delete_document(args.directory, args.prefix, docs)
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
    create.add_argument("--digits", type=int, default=3, help=_("numeric width"))
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


def cmd_item_add(args: argparse.Namespace) -> None:
    """Create a new requirement item under a document."""
    base: dict[str, Any] = {}
    data_path = getattr(args, "data", None)
    if data_path:
        with open(data_path, encoding="utf-8") as fh:
            base = json.load(fh)
    try:
        payload = build_item_payload(args, base)
        req = create_requirement(args.directory, prefix=args.prefix, data=payload)
    except DocumentNotFoundError:
        sys.stdout.write(
            _("unknown document prefix: {prefix}\n").format(prefix=args.prefix)
        )
        return
    except ValidationError as exc:
        sys.stdout.write(_("{msg}\n").format(msg=str(exc)))
        return
    sys.stdout.write(f"{req.rid}\n")


def cmd_item_move(args: argparse.Namespace) -> None:
    """Move existing item ``rid`` to document ``new_prefix``."""

    prefix, item_id = parse_rid(args.rid)
    src_dir = Path(args.directory) / prefix
    src_doc = load_document(src_dir)
    data, _mtime = load_item(src_dir, src_doc, item_id)
    src_path = locate_item_path(src_dir, src_doc, item_id)

    template: Mapping[str, Any] = {}
    data_path = getattr(args, "data", None)
    if data_path:
        with open(data_path, encoding="utf-8") as fh:
            template = json.load(fh)

    base_payload: dict[str, Any] = dict(data)
    base_payload.update(template)

    try:
        payload = build_item_payload(args, base_payload)
    except ValidationError as exc:
        sys.stdout.write(_("{msg}\n").format(msg=str(exc)))
        return

    docs = load_documents(args.directory)
    dst_doc = docs.get(args.new_prefix)
    if dst_doc is None:
        sys.stdout.write(
            _("unknown document prefix: {prefix}\n").format(prefix=args.new_prefix)
        )
        return

    labels = list(payload.get("labels", []))
    err = validate_labels(args.new_prefix, labels, docs)
    if err:
        sys.stdout.write(_("{msg}\n").format(msg=err))
        return
    payload["labels"] = labels

    dst_dir = Path(args.directory) / args.new_prefix
    new_id = next_item_id(dst_dir, dst_doc)
    payload["id"] = new_id
    if "revision" not in payload and "revision" in data:
        payload["revision"] = data["revision"]

    req = requirement_from_dict(
        payload, doc_prefix=args.new_prefix, rid=rid_for(dst_doc, new_id)
    )
    save_item(dst_dir, dst_doc, requirement_to_dict(req))
    src_path.unlink()
    alt_path = item_path(src_dir, src_doc, item_id)
    if alt_path != src_path and alt_path.exists():
        alt_path.unlink()
    sys.stdout.write(f"{req.rid}\n")


def cmd_item_delete(args: argparse.Namespace) -> None:
    """Delete requirement ``rid`` and update references."""

    docs = load_documents(args.directory)
    if getattr(args, "dry_run", False):
        exists, refs = plan_delete_item(args.directory, args.rid, docs)
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
    removed = delete_item(args.directory, args.rid, docs)
    if removed:
        sys.stdout.write(f"{args.rid}\n")
    else:
        sys.stdout.write(_("item not found: {rid}\n").format(rid=args.rid))


def add_item_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for ``item`` subcommands."""

    sub = p.add_subparsers(dest="item_command", required=True)

    add_p = sub.add_parser("add", help=_("create new item"))
    add_p.add_argument("directory", help=_("requirements root"))
    add_p.add_argument("prefix", help=_("document prefix"))
    add_p.add_argument("--title", help=_("item title"))
    add_p.add_argument("--statement", help=_("item statement"))
    add_p.add_argument("--type", choices=REQ_TYPE_CHOICES, default=RequirementType.REQUIREMENT.value)
    add_p.add_argument("--status", choices=STATUS_CHOICES, default=Status.DRAFT.value)
    add_p.add_argument("--owner", default="")
    add_p.add_argument("--priority", choices=PRIORITY_CHOICES, default=Priority.MEDIUM.value)
    add_p.add_argument("--source", default="")
    add_p.add_argument("--verification", choices=VERIFICATION_CHOICES, default=Verification.ANALYSIS.value)
    add_p.add_argument("--acceptance")
    add_p.add_argument("--conditions")
    add_p.add_argument("--rationale")
    add_p.add_argument("--assumptions")
    add_p.add_argument("--modified-at", dest="modified_at")
    add_p.add_argument("--approved-at", dest="approved_at")
    add_p.add_argument("--notes")
    add_p.add_argument("--attachments", help=_("JSON list of attachments"))
    add_p.add_argument("--labels", dest="labels", help=_("comma-separated labels"))
    add_p.add_argument("--links", help=_("comma-separated parent requirement IDs"))
    add_p.add_argument("--data", help=_("JSON template file"))
    add_p.set_defaults(func=cmd_item_add)

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


def cmd_link(args: argparse.Namespace) -> None:
    """Add links from requirement ``rid`` to ``parents``."""

    docs = load_documents(args.directory)
    try:
        prefix, item_id = parse_rid(args.rid)
    except ValueError:
        sys.stdout.write(_("invalid requirement identifier: {rid}\n").format(rid=args.rid))
        return
    doc = docs.get(prefix)
    if doc is None:
        sys.stdout.write(_("unknown document prefix: {prefix}\n").format(prefix=prefix))
        return
    item_dir = Path(args.directory) / prefix
    try:
        data, _mtime = load_item(item_dir, doc, item_id)
    except FileNotFoundError:
        sys.stdout.write(_("item not found: {rid}\n").format(rid=args.rid))
        return
    for rid in args.parents:
        if rid == args.rid:
            sys.stdout.write(_("invalid link target: {rid}\n").format(rid=rid))
            return
        try:
            parent_prefix, parent_id = parse_rid(rid)
        except ValueError:
            sys.stdout.write(_("invalid requirement identifier: {rid}\n").format(rid=rid))
            return
        if parent_prefix not in docs:
            sys.stdout.write(_("unknown document prefix: {prefix}\n").format(prefix=parent_prefix))
            return
        if not is_ancestor(prefix, parent_prefix, docs):
            sys.stdout.write(_("invalid link target: {rid}\n").format(rid=rid))
            return
        parent_dir = Path(args.directory) / parent_prefix
        parent_doc = docs[parent_prefix]
        try:
            load_item(parent_dir, parent_doc, parent_id)
        except FileNotFoundError:
            sys.stdout.write(_("linked item not found: {rid}\n").format(rid=rid))
            return
    links = set(data.get("links", []))
    if args.replace:
        links.clear()
    links.update(args.parents)
    data["links"] = sorted(links)
    save_item(item_dir, doc, data)
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


def cmd_trace(args: argparse.Namespace) -> None:
    """Export links in the chosen format."""

    links = iter_links(args.directory)
    out: TextIO
    close_out = False
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out = out_path.open("w", encoding="utf-8", newline="")
        close_out = True
    else:
        out = sys.stdout
    try:
        if args.format == "csv":
            writer = csv.writer(out)
            writer.writerow(["child", "parent"])
            for child, parent in links:
                writer.writerow([child, parent])
        elif args.format == "html":
            out.write("<!DOCTYPE html>\n<html><head><meta charset='utf-8'>\n")
            out.write("<style>table{border-collapse:collapse;}"\
                      "th,td{border:1px solid #ccc;padding:4px;text-align:left;}"\
                      "</style></head><body>\n<table>\n")
            out.write("<thead><tr><th>child</th><th>parent</th></tr></thead>\n")
            out.write("<tbody>\n")
            for child, parent in links:
                c = html.escape(child)
                p = html.escape(parent)
                out.write(f"<tr><td>{c}</td><td>{p}</td></tr>\n")
            out.write("</tbody>\n</table>\n</body></html>\n")
        else:
            for child, parent in links:
                out.write(f"{child} {parent}\n")
    finally:
        if close_out:
            out.close()


def add_trace_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for the ``trace`` command."""

    p.add_argument("directory", help=_("requirements root"))
    p.add_argument(
        "--format",
        choices=["plain", "csv", "html"],
        default="plain",
        help=_("output format"),
    )
    p.add_argument(
        "-o",
        "--output",
        help=_("write result to file"),
    )


def cmd_check(args: argparse.Namespace) -> None:
    """Verify LLM and MCP connectivity using loaded settings."""
    from app.agent import LocalAgent

    agent = LocalAgent(settings=args.app_settings, confirm=confirm)
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
    "doc": Command(lambda args: args.func(args), _("manage documents"), add_doc_arguments),
    "item": Command(lambda args: args.func(args), _("manage items"), add_item_arguments),
    "link": Command(cmd_link, _("link requirements"), add_link_arguments),
    "trace": Command(cmd_trace, _("export trace links"), add_trace_arguments),
    "check": Command(cmd_check, _("verify LLM and MCP settings"), add_check_arguments),
}
