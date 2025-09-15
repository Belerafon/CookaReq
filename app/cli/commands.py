"""Command implementations for the CLI interface."""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from app.confirm import confirm
from app.core.doc_store import (
    Document,
    is_ancestor,
    load_documents,
    iter_links,
    item_path,
    load_document,
    load_item,
    next_item_id,
    parse_rid,
    rid_for,
    save_document,
    save_item,
    delete_document,
    delete_item,
    plan_delete_document,
    plan_delete_item,
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
from tools.migrate_to_docs import migrate_to_docs

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
    docs = load_documents(args.directory)
    doc = docs.get(args.prefix)
    if doc is None:
        sys.stdout.write(_("unknown document prefix: {prefix}\n").format(prefix=args.prefix))
        return
    base: dict[str, Any] = {}
    data_path = getattr(args, "data", None)
    if data_path:
        with open(data_path, encoding="utf-8") as fh:
            base = json.load(fh)
    labels: list[str] = list(base.get("labels", []))
    labels_arg = getattr(args, "labels", None)
    if labels_arg is not None:
        labels = [t.strip() for t in labels_arg.split(",") if t.strip()]
    err = validate_labels(args.prefix, labels, docs)
    if err:
        sys.stdout.write(_("{msg}\n").format(msg=err))
        return
    links: list[str] = list(base.get("links", []))
    links_arg = getattr(args, "links", None)
    if links_arg:
        links = [t.strip() for t in links_arg.split(",") if t.strip()]
    attachments = base.get("attachments", [])
    attachments_arg = getattr(args, "attachments", None)
    if attachments_arg:
        attachments = json.loads(attachments_arg)
    item_id = next_item_id(Path(args.directory) / args.prefix, doc)
    data = {
        "id": item_id,
        "title": getattr(args, "title", None) or base.get("title", ""),
        "statement": getattr(args, "statement", None) or base.get("statement", ""),
        "type": getattr(args, "type", None)
        or base.get("type", RequirementType.REQUIREMENT.value),
        "status": getattr(args, "status", None)
        or base.get("status", Status.DRAFT.value),
        "owner": getattr(args, "owner", None) or base.get("owner", ""),
        "priority": getattr(args, "priority", None)
        or base.get("priority", Priority.MEDIUM.value),
        "source": getattr(args, "source", None) or base.get("source", ""),
        "verification": getattr(args, "verification", None)
        or base.get("verification", Verification.ANALYSIS.value),
        "acceptance": getattr(args, "acceptance", None)
        if getattr(args, "acceptance", None) is not None
        else base.get("acceptance"),
        "conditions": getattr(args, "conditions", None) or base.get("conditions", ""),
        "rationale": getattr(args, "rationale", None) or base.get("rationale", ""),
        "assumptions": getattr(args, "assumptions", None) or base.get("assumptions", ""),
        "version": getattr(args, "version", None) or base.get("version", ""),
        "modified_at": getattr(args, "modified_at", None) or base.get("modified_at", ""),
        "labels": labels,
        "attachments": attachments,
        "revision": base.get("revision", 1),
        "approved_at": getattr(args, "approved_at", None)
        if getattr(args, "approved_at", None) is not None
        else base.get("approved_at"),
        "notes": getattr(args, "notes", None) or base.get("notes", ""),
        "links": links,
    }
    doc_dir = Path(args.directory) / args.prefix
    req = requirement_from_dict(data, doc_prefix=args.prefix, rid=rid_for(doc, item_id))
    save_item(doc_dir, doc, requirement_to_dict(req))
    sys.stdout.write(f"{req.rid}\n")


def cmd_item_move(args: argparse.Namespace) -> None:
    """Move existing item ``rid`` to document ``new_prefix``."""
    prefix, item_id = parse_rid(args.rid)
    src_dir = Path(args.directory) / prefix
    src_doc = load_document(src_dir)
    data, _mtime = load_item(src_dir, src_doc, item_id)
    item_path(src_dir, src_doc, item_id).unlink()
    base: dict[str, Any] = {}
    data_path = getattr(args, "data", None)
    if data_path:
        with open(data_path, encoding="utf-8") as fh:
            base = json.load(fh)
    data.update(base)
    if getattr(args, "title", None) is not None:
        data["title"] = args.title
    if getattr(args, "statement", None) is not None:
        data["statement"] = args.statement
    if getattr(args, "type", None) is not None:
        data["type"] = args.type
    if getattr(args, "status", None) is not None:
        data["status"] = args.status
    if getattr(args, "owner", None) is not None:
        data["owner"] = args.owner
    if getattr(args, "priority", None) is not None:
        data["priority"] = args.priority
    if getattr(args, "source", None) is not None:
        data["source"] = args.source
    if getattr(args, "verification", None) is not None:
        data["verification"] = args.verification
    if getattr(args, "acceptance", None) is not None:
        data["acceptance"] = args.acceptance
    if getattr(args, "conditions", None) is not None:
        data["conditions"] = args.conditions
    if getattr(args, "rationale", None) is not None:
        data["rationale"] = args.rationale
    if getattr(args, "assumptions", None) is not None:
        data["assumptions"] = args.assumptions
    if getattr(args, "version", None) is not None:
        data["version"] = args.version
    if getattr(args, "modified_at", None) is not None:
        data["modified_at"] = args.modified_at
    if getattr(args, "approved_at", None) is not None:
        data["approved_at"] = args.approved_at
    if getattr(args, "notes", None) is not None:
        data["notes"] = args.notes
    links_arg = getattr(args, "links", None)
    if links_arg:
        data["links"] = [t.strip() for t in links_arg.split(",") if t.strip()]
    attachments_arg = getattr(args, "attachments", None)
    if attachments_arg:
        data["attachments"] = json.loads(attachments_arg)
    docs = load_documents(args.directory)
    dst_doc = docs.get(args.new_prefix)
    if dst_doc is None:
        sys.stdout.write(_("unknown document prefix: {prefix}\n").format(prefix=args.new_prefix))
        return
    labels = list(data.get("labels", []))
    labels_arg = getattr(args, "labels", None)
    if labels_arg is not None:
        labels = [t.strip() for t in labels_arg.split(",") if t.strip()]
    err = validate_labels(args.new_prefix, labels, docs)
    if err:
        sys.stdout.write(_("{msg}\n").format(msg=err))
        return
    data["labels"] = labels
    dst_dir = Path(args.directory) / args.new_prefix
    new_id = next_item_id(dst_dir, dst_doc)
    data["id"] = new_id
    req = requirement_from_dict(data, doc_prefix=args.new_prefix, rid=rid_for(dst_doc, new_id))
    save_item(dst_dir, dst_doc, requirement_to_dict(req))
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
    add_p.add_argument("--version")
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
    move_p.add_argument("--version")
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


def cmd_migrate_to_docs(args: argparse.Namespace) -> None:
    """Migrate flat requirements to document structure."""

    migrate_to_docs(
        args.directory,
        rules=args.rules,
        default=args.default,
    )


def add_migrate_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for the ``migrate`` command."""

    sub = p.add_subparsers(dest="migrate_command", required=True)
    to_docs = sub.add_parser(
        "to-docs", help=_("convert flat requirements to documents"),
    )
    to_docs.add_argument("directory", help=_("requirements directory"))
    to_docs.add_argument(
        "--rules",
        help=_("assignment rules 'label:key=value->PREFIX;...'"),
    )
    to_docs.add_argument("--default", required=True, help=_("default prefix"))
    to_docs.set_defaults(func=cmd_migrate_to_docs)


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
    "migrate": Command(lambda args: args.func(args), _("migrate data"), add_migrate_arguments),
}
