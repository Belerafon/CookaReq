"""Command-line interface for CookaReq."""
from __future__ import annotations

from app.i18n import _

import argparse
import json
from pathlib import Path

from .core import model, requirements as req_ops
from .log import configure_logging
from .settings import AppSettings, load_app_settings
from .agent import LocalAgent


def cmd_list(args: argparse.Namespace) -> None:
    """List requirements in directory, optionally filtered."""
    reqs = req_ops.search_requirements(
        args.directory, labels=args.labels, query=args.query, fields=args.fields
    )
    for r in reqs:
        print(f"{r.id}: {r.title}")


def cmd_add(args: argparse.Namespace) -> None:
    """Add requirement from JSON file to directory."""
    with open(args.file, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    path = req_ops.save_requirement(args.directory, data)
    print(path)


def cmd_edit(args: argparse.Namespace) -> None:
    """Edit existing requirement using data from JSON file."""
    with open(args.file, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    mtime = None
    try:
        _, mtime = req_ops.load_requirement(args.directory, data["id"])
    except FileNotFoundError:
        pass
    path = req_ops.save_requirement(args.directory, data, mtime=mtime)
    print(path)


def cmd_show(args: argparse.Namespace) -> None:
    """Show detailed JSON for requirement with *id*."""
    req = req_ops.get_requirement(args.directory, args.id)
    data = model.requirement_to_dict(req)
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_check(args: argparse.Namespace) -> None:
    """Verify LLM and MCP connectivity using loaded settings."""

    agent = LocalAgent(settings=args.app_settings)
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
    p_list.set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help=_("add requirement from JSON file"))
    p_add.add_argument("directory", help=_("requirements directory"))
    p_add.add_argument("file", help=_("JSON file with requirement"))
    p_add.set_defaults(func=cmd_add)

    p_edit = sub.add_parser("edit", help=_("edit requirement from JSON file"))
    p_edit.add_argument("directory", help=_("requirements directory"))
    p_edit.add_argument("file", help=_("JSON file with updated requirement"))
    p_edit.set_defaults(func=cmd_edit)

    p_show = sub.add_parser("show", help=_("show requirement details"))
    p_show.add_argument("directory", help=_("requirements directory"))
    p_show.add_argument("id", type=int, help=_("requirement id"))
    p_show.set_defaults(func=cmd_show)

    p_check = sub.add_parser("check", help=_("verify LLM and MCP settings"))
    p_check.add_argument("--llm", action="store_true", help=_("check only LLM"))
    p_check.add_argument("--mcp", action="store_true", help=_("check only MCP"))
    p_check.set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = AppSettings()
    if args.settings:
        settings = load_app_settings(args.settings)
    args.app_settings = settings
    args.func(args)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
