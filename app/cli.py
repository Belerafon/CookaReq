"""Command-line interface for CookaReq."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import store, search, model


def _load_all(directory: str | Path) -> list[model.Requirement]:
    """Load all requirements from *directory*."""
    reqs: list[model.Requirement] = []
    for path in Path(directory).glob("*.json"):
        data, _ = store.load(path)
        reqs.append(model.Requirement(**data))
    return reqs


def cmd_list(args: argparse.Namespace) -> None:
    """List requirements in directory, optionally filtered."""
    reqs = _load_all(args.directory)
    reqs = search.search(reqs, labels=args.labels, query=args.query, fields=args.fields)
    for r in reqs:
        print(f"{r.id}: {r.title}")


def cmd_add(args: argparse.Namespace) -> None:
    """Add requirement from JSON file to directory."""
    with open(args.file, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    path = store.save(args.directory, data)
    print(path)


def cmd_show(args: argparse.Namespace) -> None:
    """Show detailed JSON for requirement with *id*."""
    fname = store.filename_for(args.id)
    path = Path(args.directory) / fname
    data, _ = store.load(path)
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CookaReq CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="list requirements")
    p_list.add_argument("directory", help="requirements directory")
    p_list.add_argument("--labels", nargs="*", default=[], help="filter by labels")
    p_list.add_argument("--query", help="text search query")
    p_list.add_argument("--fields", nargs="*", help="fields for text search")
    p_list.set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="add requirement from JSON file")
    p_add.add_argument("directory", help="requirements directory")
    p_add.add_argument("file", help="JSON file with requirement")
    p_add.set_defaults(func=cmd_add)

    p_show = sub.add_parser("show", help="show requirement details")
    p_show.add_argument("directory", help="requirements directory")
    p_show.add_argument("id", help="requirement id")
    p_show.set_defaults(func=cmd_show)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
