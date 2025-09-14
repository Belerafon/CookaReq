"""Command implementations for the CLI interface."""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

from app.confirm import confirm
from app.core import model
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
    collect_labels,
)
from app.core.repository import RequirementRepository
from app.i18n import _
from tools.migrate_to_docs import migrate_to_docs


@dataclass
class Command:
    """Describe a CLI command and its argument handler."""

    func: Callable[[argparse.Namespace, RequirementRepository], None]
    help: str
    add_arguments: Callable[[argparse.ArgumentParser], None]


def cmd_list(args: argparse.Namespace, repo: RequirementRepository) -> None:
    """List requirements in directory, optionally filtered."""
    reqs = repo.search(
        args.directory,
        labels=args.labels,
        query=args.query,
        fields=args.fields,
        status=args.status,
    )
    for r in reqs:
        sys.stdout.write(f"{r.id}: {r.title}\n")


def add_list_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for the ``list`` command."""
    p.add_argument("directory", help=_("requirements directory"))
    p.add_argument("--labels", nargs="*", default=[], help=_("filter by labels"))
    p.add_argument("--query", help=_("text search query"))
    p.add_argument("--fields", nargs="*", help=_("fields for text search"))
    p.add_argument("--status", help=_("filter by status"))


def cmd_add(args: argparse.Namespace, repo: RequirementRepository) -> None:
    """Add requirement from JSON file to directory."""
    try:
        with Path(args.file).open(encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        sys.stdout.write(_("File not found: {file}\n").format(file=args.file))
        return
    except json.JSONDecodeError as exc:
        sys.stdout.write(_("Invalid JSON file: {error}\n").format(error=exc))
        return
    try:
        obj = model.requirement_from_dict(data)
    except ValueError as exc:
        sys.stdout.write(_("Invalid requirement data: {error}\n").format(error=exc))
        return
    path = repo.save(args.directory, obj, modified_at=args.modified_at)
    sys.stdout.write(f"{path}\n")


def add_add_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for the ``add`` command."""
    p.add_argument("directory", help=_("requirements directory"))
    p.add_argument("file", help=_("JSON file with requirement"))
    p.add_argument("--modified-at", help=_("explicit modified timestamp"))


def cmd_edit(args: argparse.Namespace, repo: RequirementRepository) -> None:
    """Edit existing requirement using data from JSON file."""
    try:
        with Path(args.file).open(encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        sys.stdout.write(_("File not found: {file}\n").format(file=args.file))
        return
    except json.JSONDecodeError as exc:
        sys.stdout.write(_("Invalid JSON file: {error}\n").format(error=exc))
        return
    try:
        obj = model.requirement_from_dict(data)
    except ValueError as exc:
        sys.stdout.write(_("Invalid requirement data: {error}\n").format(error=exc))
        return
    mtime = None
    with suppress(FileNotFoundError):
        mtime = repo.load(args.directory, obj.id)[1]
    path = repo.save(args.directory, obj, mtime=mtime, modified_at=args.modified_at)
    sys.stdout.write(f"{path}\n")


def add_edit_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for the ``edit`` command."""
    p.add_argument("directory", help=_("requirements directory"))
    p.add_argument("file", help=_("JSON file with updated requirement"))
    p.add_argument("--modified-at", help=_("explicit modified timestamp"))


def cmd_delete(args: argparse.Namespace, repo: RequirementRepository) -> None:
    """Delete requirement with *id* from *directory*."""
    try:
        repo.get(args.directory, args.id)
    except FileNotFoundError:
        sys.stderr.write(f"requirement {args.id} not found\n")
        return
    repo.delete(args.directory, args.id)
    sys.stdout.write("deleted\n")


def add_delete_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for the ``delete`` command."""
    p.add_argument("directory", help=_("requirements directory"))
    p.add_argument("id", type=int, help=_("requirement id"))


def cmd_clone(args: argparse.Namespace, repo: RequirementRepository) -> None:
    """Clone requirement ``source_id`` to ``new_id`` in *directory*."""
    try:
        req = repo.get(args.directory, args.source_id)
    except FileNotFoundError:
        sys.stdout.write(f"requirement {args.source_id} not found\n")
        return
    req.id = args.new_id
    req.revision = 1
    path = repo.save(args.directory, req, modified_at=args.modified_at)
    sys.stdout.write(f"{path}\n")


def add_clone_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for the ``clone`` command."""
    p.add_argument("directory", help=_("requirements directory"))
    p.add_argument("source_id", type=int, help=_("source requirement id"))
    p.add_argument("new_id", type=int, help=_("new requirement id"))
    p.add_argument("--modified-at", help=_("explicit modified timestamp"))


def cmd_show(args: argparse.Namespace, repo: RequirementRepository) -> None:
    """Show detailed JSON for requirement with *id*."""
    req = repo.get(args.directory, args.id)
    data = model.requirement_to_dict(req)
    sys.stdout.write(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def add_show_arguments(p: argparse.ArgumentParser) -> None:
    """Configure parser for the ``show`` command."""
    p.add_argument("directory", help=_("requirements directory"))
    p.add_argument("id", type=int, help=_("requirement id"))


def cmd_doc_create(args: argparse.Namespace, _repo: RequirementRepository) -> None:
    """Create new document within requirements root."""

    doc = Document(
        prefix=args.prefix,
        title=args.title,
        digits=args.digits,
        parent=args.parent,
    )
    save_document(Path(args.directory) / args.prefix, doc)
    sys.stdout.write(f"{args.prefix}\n")


def cmd_doc_list(args: argparse.Namespace, _repo: RequirementRepository) -> None:
    """List documents configured under requirements root."""

    root = Path(args.directory)
    for path in sorted(root.iterdir()):
        if (path / "document.json").is_file():
            doc = load_document(path)
            sys.stdout.write(f"{doc.prefix} {doc.title}\n")


def cmd_doc_delete(args: argparse.Namespace, _repo: RequirementRepository) -> None:
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


def cmd_item_add(args: argparse.Namespace, _repo: RequirementRepository) -> None:
    """Create a new requirement item under a document."""

    docs = load_documents(args.directory)
    doc = docs.get(args.prefix)
    if doc is None:
        sys.stdout.write(_("unknown document prefix: {prefix}\n").format(prefix=args.prefix))
        return
    allowed, freeform = collect_labels(args.prefix, docs)
    labels: list[str] = []
    if args.labels:
        labels = [t.strip() for t in args.labels.split(",") if t.strip()]
        if not freeform:
            unknown = [lbl for lbl in labels if lbl not in allowed]
            if unknown:
                sys.stdout.write(_("unknown label: {name}\n").format(name=unknown[0]))
                return
    doc_dir = Path(args.directory) / args.prefix
    item_id = next_item_id(doc_dir, doc)
    data = {
        "id": item_id,
        "title": args.title,
        "text": args.text,
        "labels": labels,
        "links": [],
    }
    save_item(doc_dir, doc, data)
    sys.stdout.write(f"{rid_for(doc, item_id)}\n")


def cmd_item_move(args: argparse.Namespace, _repo: RequirementRepository) -> None:
    """Move existing item ``rid`` to document ``new_prefix``."""

    prefix, item_id = parse_rid(args.rid)
    src_dir = Path(args.directory) / prefix
    src_doc = load_document(src_dir)
    data, _mtime = load_item(src_dir, src_doc, item_id)
    item_path(src_dir, src_doc, item_id).unlink()
    dst_dir = Path(args.directory) / args.new_prefix
    dst_doc = load_document(dst_dir)
    new_id = next_item_id(dst_dir, dst_doc)
    data["id"] = new_id
    save_item(dst_dir, dst_doc, data)
    sys.stdout.write(f"{rid_for(dst_doc, new_id)}\n")


def cmd_item_delete(args: argparse.Namespace, _repo: RequirementRepository) -> None:
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
    add_p.add_argument("--title", required=True, help=_("item title"))
    add_p.add_argument("--text", required=True, help=_("item text"))
    add_p.add_argument("--labels", dest="labels", help=_("comma-separated labels"))
    add_p.set_defaults(func=cmd_item_add)

    move_p = sub.add_parser("move", help=_("move item"))
    move_p.add_argument("directory", help=_("requirements root"))
    move_p.add_argument("rid", help=_("requirement identifier"))
    move_p.add_argument("new_prefix", help=_("target document prefix"))
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


def cmd_link(args: argparse.Namespace, _repo: RequirementRepository) -> None:
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


def cmd_trace(args: argparse.Namespace, _repo: RequirementRepository) -> None:
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


def cmd_migrate_to_docs(
    args: argparse.Namespace, _repo: RequirementRepository
) -> None:
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


def cmd_check(args: argparse.Namespace, _repo: RequirementRepository) -> None:
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
    "list": Command(cmd_list, _("list requirements"), add_list_arguments),
    "add": Command(cmd_add, _("add requirement from JSON file"), add_add_arguments),
    "edit": Command(cmd_edit, _("edit requirement from JSON file"), add_edit_arguments),
    "delete": Command(cmd_delete, _("delete requirement"), add_delete_arguments),
    "clone": Command(cmd_clone, _("clone requirement"), add_clone_arguments),
    "show": Command(cmd_show, _("show requirement details"), add_show_arguments),
    "doc": Command(lambda args, repo: args.func(args, repo), _("manage documents"), add_doc_arguments),
    "item": Command(lambda args, repo: args.func(args, repo), _("manage items"), add_item_arguments),
    "link": Command(cmd_link, _("link requirements"), add_link_arguments),
    "trace": Command(cmd_trace, _("export trace links"), add_trace_arguments),
    "check": Command(cmd_check, _("verify LLM and MCP settings"), add_check_arguments),
    "migrate": Command(lambda args, repo: args.func(args, repo), _("migrate data"), add_migrate_arguments),
}
