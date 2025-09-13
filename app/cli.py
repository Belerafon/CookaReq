"""Command-line interface for CookaReq."""
from __future__ import annotations

import os
import sys
import atexit
from pathlib import Path
from app import i18n
from app.i18n import _

import argparse
import json
from .core import model
from .core.repository import RequirementRepository, FileRequirementRepository
from .log import configure_logging
from .settings import AppSettings, load_app_settings
from .agent import LocalAgent
from .confirm import confirm, set_confirm, auto_confirm

APP_NAME = "CookaReq"
LOCALE_DIR = os.path.join(os.path.dirname(__file__), "locale")
MISSING_PATH = Path(LOCALE_DIR) / "missing.po"
atexit.register(i18n.flush_missing, MISSING_PATH)

set_confirm(auto_confirm)


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
    path = repo.save(args.directory, obj)
    print(path)


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
    path = repo.save(args.directory, obj, mtime=mtime)
    print(path)


def cmd_delete(args: argparse.Namespace, repo: RequirementRepository) -> None:
    """Delete requirement with *id* from *directory*."""
    try:
        # Ensure requirement exists to report errors for invalid ids
        repo.get(args.directory, args.id)
    except FileNotFoundError:
        print(f"requirement {args.id} not found", file=sys.stderr)
        return
    repo.delete(args.directory, args.id)
    print("deleted")


def cmd_show(args: argparse.Namespace, repo: RequirementRepository) -> None:
    """Show detailed JSON for requirement with *id*."""
    req = repo.get(args.directory, args.id)
    data = model.requirement_to_dict(req)
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_check(args: argparse.Namespace, _repo: RequirementRepository) -> None:
    """Verify LLM and MCP connectivity using loaded settings."""

    agent = LocalAgent(settings=args.app_settings, confirm=confirm)
    results: dict[str, object] = {}
    if args.llm or not (args.llm or args.mcp):
        results["llm"] = agent.check_llm()
    if args.mcp or not (args.llm or args.mcp):
        results["mcp"] = agent.check_tools()
    print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=_("CookaReq CLI"))
    parser.add_argument(
        "--settings",
        help=_("path to JSON/TOML settings"),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help=_("list requirements"))
    p_list.add_argument("directory", help=_("requirements directory"))
    p_list.add_argument("--labels", nargs="*", default=[], help=_("filter by labels"))
    p_list.add_argument("--query", help=_("text search query"))
    p_list.add_argument("--fields", nargs="*", help=_("fields for text search"))
    p_list.add_argument("--status", help=_("filter by status"))
    p_list.set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help=_("add requirement from JSON file"))
    p_add.add_argument("directory", help=_("requirements directory"))
    p_add.add_argument("file", help=_("JSON file with requirement"))
    p_add.set_defaults(func=cmd_add)

    p_edit = sub.add_parser("edit", help=_("edit requirement from JSON file"))
    p_edit.add_argument("directory", help=_("requirements directory"))
    p_edit.add_argument("file", help=_("JSON file with updated requirement"))
    p_edit.set_defaults(func=cmd_edit)

    p_delete = sub.add_parser("delete", help=_("delete requirement"))
    p_delete.add_argument("directory", help=_("requirements directory"))
    p_delete.add_argument("id", type=int, help=_("requirement id"))
    p_delete.set_defaults(func=cmd_delete)

    p_show = sub.add_parser("show", help=_("show requirement details"))
    p_show.add_argument("directory", help=_("requirements directory"))
    p_show.add_argument("id", type=int, help=_("requirement id"))
    p_show.set_defaults(func=cmd_show)

    p_check = sub.add_parser("check", help=_("verify LLM and MCP settings"))
    p_check.add_argument("--llm", action="store_true", help=_("check only LLM"))
    p_check.add_argument("--mcp", action="store_true", help=_("check only MCP"))
    p_check.set_defaults(func=cmd_check)

    return parser


def main(
    argv: list[str] | None = None,
    repo: RequirementRepository | None = None,
) -> int:
    """CLI entry point."""
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = AppSettings()
    if args.settings:
        settings = load_app_settings(args.settings)
    args.app_settings = settings
    repository = repo or FileRequirementRepository()
    args.func(args, repository)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
