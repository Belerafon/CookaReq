"""Entry point for the command-line interface."""

from __future__ import annotations

import argparse
import atexit
from pathlib import Path

from app import i18n
from app.confirm import auto_confirm, set_confirm
from app.i18n import _
from app.log import configure_logging
from app.settings import AppSettings, load_app_settings

from .commands import COMMANDS

APP_NAME = "CookaReq"
LOCALE_DIR = Path(__file__).resolve().parent.parent / "locale"
MISSING_PATH = LOCALE_DIR / "missing.po"
atexit.register(i18n.flush_missing, MISSING_PATH)

set_confirm(auto_confirm)


def build_parser() -> argparse.ArgumentParser:
    """Construct argument parser for CLI commands."""
    parser = argparse.ArgumentParser(description=_("CookaReq CLI"))
    parser.add_argument(
        "--settings",
        help=_("path to JSON/TOML settings"),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, cmd in COMMANDS.items():
        p = sub.add_parser(name, help=cmd.help)
        cmd.add_arguments(p)
        p.set_defaults(func=cmd.func)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
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
