"""Build the CookaReq application using PyInstaller.

This script generates a one-folder distribution in the ``dist``
folder. It requires PyInstaller to be installed in the active
environment.
"""
from pathlib import Path

import PyInstaller.__main__  # type: ignore


def main() -> None:
    root = Path(__file__).resolve().parent
    script = root / "app" / "main.py"
    PyInstaller.__main__.run(
        [
            str(script),
            "--name=CookaReq",
            "--onedir",
            "--noconfirm",
            "--windowed",
        ]
    )


if __name__ == "__main__":
    main()
