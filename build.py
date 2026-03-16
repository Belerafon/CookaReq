"""Build the CookaReq application using PyInstaller.

This script generates a one-folder distribution in the ``dist``
folder. It requires PyInstaller to be installed in the active
environment.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


SUPPORTED_PYTHON = (3, 12)

def get_git_commit_date() -> str | None:
    """Get the date of the last commit from git."""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%cs"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def update_version_json() -> None:
    """Update version.json with the current git commit date."""
    root = Path(__file__).resolve().parent
    version_file = root / "app" / "resources" / "version.json"
    
    commit_date = get_git_commit_date()
    if commit_date:
        version_file.write_text(
            json.dumps({"date": commit_date}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Updated version.json with commit date: {commit_date}")
    else:
        print("Could not get git commit date, keeping existing version.json")


def clean_build_dirs() -> None:
    """Remove build and dist directories if they exist."""
    root = Path(__file__).resolve().parent
    for dir_name in ('build', 'dist'):
        dir_path = root / dir_name
        if dir_path.exists():
            print(f"Removing {dir_path}...")
            shutil.rmtree(dir_path, ignore_errors=True)


def ensure_supported_python() -> None:
    """Abort build when Python runtime is outside the supported minor version."""
    current = (sys.version_info.major, sys.version_info.minor)
    if current != SUPPORTED_PYTHON:
        required = ".".join(str(part) for part in SUPPORTED_PYTHON)
        got = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        raise SystemExit(
            "CookaReq build requires Python "
            f"{required}.x; current interpreter is {got}. "
            "Use Python 3.12 to avoid missing binary wheels (for example jiter/openai) "
            "and unsupported PyInstaller hooks."
        )


def _build_pyinstaller_args(
    *,
    script: Path,
    root: Path,
    icon: Path,
    hidden_imports: list[str],
    collect_all_packages: list[str],
    collect_data_packages: list[str],
    excluded_modules: list[str],
    onefile: bool,
) -> list[str]:
    """Return PyInstaller CLI arguments for the current build configuration."""
    args: list[str] = [
        str(script),
        "--name=CookaReq",
        "--noconfirm",
        "--windowed",
        "--onedir",
        f"--paths={root}",
        *[f"--hidden-import={pkg}" for pkg in hidden_imports],
        *[f"--collect-all={pkg}" for pkg in collect_all_packages],
        *[f"--collect-data={pkg}" for pkg in collect_data_packages],
        f"--add-data={(root / 'app' / 'resources')}{os.pathsep}app/resources",
        f"--add-data={(root / 'app' / 'ui' / 'resources')}{os.pathsep}app/ui/resources",
        f"--add-data={(root / 'app' / 'locale')}{os.pathsep}app/locale",
        f"--icon={icon}",
        "--clean",
        "--noconsole",
        *[f"--exclude-module={module}" for module in excluded_modules],
        "--hidden-import=wx.lib.pubsub.setupkwargs",
        "--hidden-import=wx.lib.pubsub.core",
        "--hidden-import=wx.lib.pubsub.core.arg1",
        "--hidden-import=wx.lib.pubsub.core.kwargs",
        "--hidden-import=wx.lib.pubsub.utils",
    ]

    if onefile:
        return [a for a in args if a != "--onedir"] + ["--onefile"]
    return args


def main() -> None:
    """Build project executables using PyInstaller."""
    import PyInstaller.__main__  # type: ignore

    ensure_supported_python()

    # Update version.json with current git commit date
    update_version_json()
    
    # Clean up previous build artifacts
    clean_build_dirs()
    
    root = Path(__file__).resolve().parent
    # Use __main__.py as the entry point to ensure proper package structure
    script = root / "app" / "__main__.py"
    icon = root / "app" / "resources" / "app.ico"
    # Get all required packages from pyproject.toml and dependencies
    required_packages = [
        # Main application packages
        "wx",
        "jsonschema",
        "charset_normalizer",
        "fastapi",
        "uvicorn",
        "mcp",
        "openai",
        "markdown",
        "reportlab",
        "typer",
        "python_multipart",
        "latex2mathml",
        "mathml2omml",
        
        # Core dependencies
        "pydantic",
        "typing_extensions",
        "anyio",
        "click",
        "h11",
        "yaml",
        "httpx",
        "python_dotenv",
        "pydantic_settings",
        "sse_starlette",
        "pywin32",
        "pypubsub",
        "polib",  # Required for i18n
        
        # Submodules that might be imported dynamically
        "uvicorn.loops",
        "uvicorn.protocols",
        "uvicorn.lifespan",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
    ]

    # Add the app directory to the Python path
    import sys
    sys.path.insert(0, str(root))
    
    # Add hidden imports for PyInstaller
    hidden_imports = [
        # Add any dynamically imported modules here
        "pkg_resources.py2_warn",
        "pkg_resources.markers",
        "pydantic",
        "pydantic_core",
        "polib",  # Explicitly add polib
        "email.mime.multipart",
        "email.mime.text",
        "email.mime.base",
        "email.mime.nonmultipart",
        "email.mime.application",
        "email.mime.audio",
        "email.mime.image",
        "email.mime.message",
        "email.encoders",
        "email.charset",
        "email.policy",
        "email.utils",
        "email._parseaddr",
        "email._policybase",
        "email.base64mime",
        "email.quoprimime",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "matplotlib",
        "matplotlib.pyplot",
        "matplotlib.backends.backend_agg",
        "matplotlib.mathtext",
        "latex2mathml",
        "latex2mathml.converter",
        "mathml2omml",
    ]

    # Add all required packages to hidden imports
    hidden_imports.extend(required_packages)

    collect_all_packages = [
        "jsonschema",
        "fastapi",
        "uvicorn",
        "markdown",
        "reportlab",
        "mcp",
        "typer",
        # Formula conversion path for DOCX export (LaTeX → MathML → OMML).
        "latex2mathml",
        "mathml2omml",
    ]

    # Keep formula preview assets without full package graph scan, which tries
    # to import optional test modules and unavailable platform bindings.
    collect_data_packages = [
        "matplotlib",
    ]

    excluded_modules = [
        "_tkinter",
        "test",
        "setuptools",
        "pip",
        # Keep scientific stack exclusions except modules used by formula preview.
        "scipy",
        "pandas",
        "sklearn",
        "torch",
        # Optional cairo binding is not required by the app and fails often on
        # clean Windows hosts without cairo DLL.
        "wx.lib.wxcairo",
        # Matplotlib test package is never needed at runtime.
        "matplotlib.tests",
    ]

    args = _build_pyinstaller_args(
        script=script,
        root=root,
        icon=icon,
        hidden_imports=hidden_imports,
        collect_all_packages=collect_all_packages,
        collect_data_packages=collect_data_packages,
        excluded_modules=excluded_modules,
        onefile=any(a == "--onefile" for a in sys.argv[1:]),
    )

    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
