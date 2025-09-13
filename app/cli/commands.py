"""Command implementations for the CLI interface."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Callable

from app.core import model
from app.core.repository import RequirementRepository
from app.agent import LocalAgent
from app.confirm import confirm
from app.i18n import _


@dataclass
class Command:
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
        print(f"{r.id}: {r.title}")


def add_list_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("directory", help=_("requirements directory"))
    p.add_argument("--labels", nargs="*", default=[], help=_("filter by labels"))
    p.add_argument("--query", help=_("text search query"))
    p.add_argument("--fields", nargs="*", help=_("fields for text search"))
    p.add_argument("--status", help=_("filter by status"))


def cmd_add(args: argparse.Namespace, repo: RequirementRepository) -> None:
    """Add requirement from JSON file to directory."""
    try:
        with open(args.file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(_("Invalid JSON file: {error}").format(error=exc))
        return
    try:
        obj = model.requirement_from_dict(data)
    except ValueError as exc:
        print(_("Invalid requirement data: {error}").format(error=exc))
        return
    path = repo.save(args.directory, obj, modified_at=args.modified_at)
    print(path)


def add_add_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("directory", help=_("requirements directory"))
    p.add_argument("file", help=_("JSON file with requirement"))
    p.add_argument("--modified-at", help=_("explicit modified timestamp"))


def cmd_edit(args: argparse.Namespace, repo: RequirementRepository) -> None:
    """Edit existing requirement using data from JSON file."""
    try:
        with open(args.file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(_("Invalid JSON file: {error}").format(error=exc))
        return
    try:
        obj = model.requirement_from_dict(data)
    except ValueError as exc:
        print(_("Invalid requirement data: {error}").format(error=exc))
        return
    mtime = None
    try:
        mtime = repo.load(args.directory, obj.id)[1]
    except FileNotFoundError:
        pass
    path = repo.save(args.directory, obj, mtime=mtime, modified_at=args.modified_at)
    print(path)


def add_edit_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("directory", help=_("requirements directory"))
    p.add_argument("file", help=_("JSON file with updated requirement"))
    p.add_argument("--modified-at", help=_("explicit modified timestamp"))


def cmd_delete(args: argparse.Namespace, repo: RequirementRepository) -> None:
    """Delete requirement with *id* from *directory*."""
    try:
        repo.get(args.directory, args.id)
    except FileNotFoundError:
        print(f"requirement {args.id} not found", file=sys.stderr)
        return
    repo.delete(args.directory, args.id)
    print("deleted")


def add_delete_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("directory", help=_("requirements directory"))
    p.add_argument("id", type=int, help=_("requirement id"))


def cmd_clone(args: argparse.Namespace, repo: RequirementRepository) -> None:
    """Clone requirement ``source_id`` to ``new_id`` in *directory*."""
    try:
        req = repo.get(args.directory, args.source_id)
    except FileNotFoundError:
        print(f"requirement {args.source_id} not found", file=sys.stderr)
        return
    req.id = args.new_id
    req.revision = 1
    path = repo.save(args.directory, req, modified_at=args.modified_at)
    print(path)


def add_clone_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("directory", help=_("requirements directory"))
    p.add_argument("source_id", type=int, help=_("source requirement id"))
    p.add_argument("new_id", type=int, help=_("new requirement id"))
    p.add_argument("--modified-at", help=_("explicit modified timestamp"))


def cmd_show(args: argparse.Namespace, repo: RequirementRepository) -> None:
    """Show detailed JSON for requirement with *id*."""
    req = repo.get(args.directory, args.id)
    data = model.requirement_to_dict(req)
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def add_show_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("directory", help=_("requirements directory"))
    p.add_argument("id", type=int, help=_("requirement id"))


def cmd_check(args: argparse.Namespace, _repo: RequirementRepository) -> None:
    """Verify LLM and MCP connectivity using loaded settings."""
    agent = LocalAgent(settings=args.app_settings, confirm=confirm)
    results: dict[str, object] = {}
    if args.llm or not (args.llm or args.mcp):
        results["llm"] = agent.check_llm()
    if args.mcp or not (args.llm or args.mcp):
        results["mcp"] = agent.check_tools()
    print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))


def add_check_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--llm", action="store_true", help=_("check only LLM"))
    p.add_argument("--mcp", action="store_true", help=_("check only MCP"))


COMMANDS: dict[str, Command] = {
    "list": Command(cmd_list, _("list requirements"), add_list_arguments),
    "add": Command(cmd_add, _("add requirement from JSON file"), add_add_arguments),
    "edit": Command(cmd_edit, _("edit requirement from JSON file"), add_edit_arguments),
    "delete": Command(cmd_delete, _("delete requirement"), add_delete_arguments),
    "clone": Command(cmd_clone, _("clone requirement"), add_clone_arguments),
    "show": Command(cmd_show, _("show requirement details"), add_show_arguments),
    "check": Command(cmd_check, _("verify LLM and MCP settings"), add_check_arguments),
}
