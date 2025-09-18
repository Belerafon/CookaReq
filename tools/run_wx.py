#!/usr/bin/env python3
"""Execute a Python script under a virtual X display for wx debugging."""

from __future__ import annotations

import argparse
import runpy
import sys
from pathlib import Path

from pyvirtualdisplay import Display


def _parse_size(value: str) -> tuple[int, int]:
    """Parse ``WIDTHxHEIGHT`` syntax into a size tuple."""

    parts = value.lower().split("x", 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            "size must be provided as WIDTHxHEIGHT, e.g. 1280x800",
        )
    try:
        width = int(parts[0])
        height = int(parts[1])
    except ValueError as exc:  # pragma: no cover - argparse surfaces message
        raise argparse.ArgumentTypeError(
            "size must contain integer width and height",
        ) from exc
    if width <= 0 or height <= 0:
        raise argparse.ArgumentTypeError("size dimensions must be positive")
    return width, height


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a Python module or script in an Xvfb-backed display so wx "
            "applications can start without a physical screen."
        )
    )
    parser.add_argument(
        "script",
        type=Path,
        help="Path to the Python script that should be executed.",
    )
    parser.add_argument(
        "script_args",
        nargs=argparse.REMAINDER,
        help=(
            "Arguments forwarded to the target script. Separate them with "
            "'--' if they look like options to this helper."
        ),
    )
    parser.add_argument(
        "--size",
        default="1280x800",
        type=_parse_size,
        help="Virtual display size in WIDTHxHEIGHT format (default: 1280x800).",
    )
    parser.add_argument(
        "--visible",
        action="store_true",
        help="Expose the virtual display window instead of keeping it headless.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point used by ``if __name__ == '__main__'``."""

    parser = _build_parser()
    args = parser.parse_args(argv)

    script_path = args.script
    if not script_path.exists():
        parser.error(f"script '{script_path}' does not exist")
    if script_path.is_dir():
        parser.error("script argument must be a file, not a directory")

    display = Display(visible=1 if args.visible else 0, size=args.size)
    display.start()
    try:
        sys.argv = [str(script_path)] + list(args.script_args)
        runpy.run_path(str(script_path), run_name="__main__")
    finally:
        display.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
