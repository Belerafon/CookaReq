"""Build the CookaReq application using PyInstaller.

This script generates a one-folder distribution in the ``dist``
folder. It requires PyInstaller to be installed in the active
environment.
"""
from pathlib import Path
import os
import sys

import PyInstaller.__main__  # type: ignore


def main() -> None:
    """Build project executables using PyInstaller."""
    root = Path(__file__).resolve().parent
    script = root / "app" / "main.py"
    icon = root / "app" / "resources" / "app.ico"
    args: list[str] = [
        str(script),
        "--name=CookaReq",
        "--noconfirm",
        "--windowed",
        # Default to one-folder; can be overridden by --onefile passed to this script
        "--onedir",
        # Be explicit to ensure third-party libs are discovered
        "--hidden-import=wx",
        "--hidden-import=jsonschema",
        # Collect package data/binaries that wx/jsonschema may need
        "--collect-all=wx",
        "--collect-all=jsonschema",
        f"--add-data={icon}{os.pathsep}app/resources",
        f"--icon={icon}",
    ]

    # Allow switching to a single EXE if user passes "--onefile"
    if any(a == "--onefile" for a in sys.argv[1:]):
        # Replace --onedir with --onefile
        args = [a for a in args if a != "--onedir"] + ["--onefile"]

    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
