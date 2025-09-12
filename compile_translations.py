"""Compile gettext .po files into .mo files."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def compile_all(locales_dir: Path) -> None:
    """Compile all ``.po`` files under ``locales_dir`` into ``.mo`` files."""
    if shutil.which("msgfmt") is None:
        print("msgfmt not found. Please install GNU gettext.", file=sys.stderr)
        raise SystemExit(1)

    for po_file in locales_dir.rglob("*.po"):
        mo_file = po_file.with_suffix(".mo")
        subprocess.run(["msgfmt", str(po_file), "-o", str(mo_file)], check=True)


def main() -> None:
    root = Path(__file__).resolve().parent
    compile_all(root / "app" / "locale")


if __name__ == "__main__":
    main()
