"""Entry point for the command-line interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from app import i18n
from app.application import ApplicationContext
from app.i18n import _
from app.log import configure_logging
from app.settings import AppSettings, load_app_settings

from .commands import COMMANDS

APP_NAME = "CookaReq"
LOCALE_DIR = Path(__file__).resolve().parent.parent / "locale"

i18n.install(APP_NAME, LOCALE_DIR)


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
    context = ApplicationContext.for_cli(app_name=APP_NAME)
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = AppSettings()
    if args.settings:
        settings = load_app_settings(args.settings)
    preferred_language = settings.ui.language
    if preferred_language:
        i18n.install(APP_NAME, LOCALE_DIR, [preferred_language])
    args.app_settings = settings
    result = args.func(args, context)
    if isinstance(result, int):
        return result
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
