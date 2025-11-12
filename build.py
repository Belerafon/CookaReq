"""Build the CookaReq application using PyInstaller.

This script generates a one-folder distribution in the ``dist``
folder. It requires PyInstaller to be installed in the active
environment.
"""

import os
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__  # type: ignore


def clean_build_dirs() -> None:
    """Remove build and dist directories if they exist."""
    root = Path(__file__).resolve().parent
    for dir_name in ('build', 'dist'):
        dir_path = root / dir_name
        if dir_path.exists():
            print(f"Removing {dir_path}...")
            shutil.rmtree(dir_path, ignore_errors=True)


def main() -> None:
    """Build project executables using PyInstaller."""
    # Clean up previous build artifacts
    clean_build_dirs()
    
    root = Path(__file__).resolve().parent
    # Use __main__.py as the entry point to ensure proper package structure
    script = root / "app" / "__main__.py"
    icon = root / "app" / "resources" / "app.ico"
    # Add data files
    datas = [
        (str(root / "app" / "resources"), "app/resources"),
        # Include ui/resources directory with all its contents
        (str(root / "app" / "ui" / "resources"), "app/ui/resources"),
    ]
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
    ]

    # Add all required packages to hidden imports
    hidden_imports.extend(required_packages)

    # Build PyInstaller arguments
    args: list[str] = [
        str(script),
        "--name=CookaReq",
        "--noconfirm",
        "--windowed",
        # Default to one-folder; can be overridden by --onefile passed to this script
        "--onedir",
        # Add the app directory to the Python path in the executable
        f"--paths={root}",
        
        # Include all required packages
        *[f"--hidden-import={pkg}" for pkg in hidden_imports],
        
        # Collect package data/binaries that may be needed
        *[f"--collect-all={pkg}" for pkg in [
            "wx", "jsonschema", "fastapi", "uvicorn", "openai", 
            "markdown", "reportlab", "mcp", "typer"
        ]],
        
        # Add resources
        f"--add-data={icon}{os.pathsep}app/resources",
        f"--add-data={(root / 'app' / 'ui' / 'resources')}{os.pathsep}app/ui/resources",
        f"--add-data={(root / 'app' / 'locale')}{os.pathsep}app/locale",
        f"--icon={icon}",
        
        # Additional PyInstaller options for better compatibility
        "--clean",
        "--noconsole",
        "--exclude-module=_tkinter",
        "--exclude-module=unittest",
        "--exclude-module=test",
        "--exclude-module=setuptools",
        "--exclude-module=pip",
        "--exclude-module=numpy",
        "--exclude-module=matplotlib",
        "--exclude-module=scipy",
        "--exclude-module=pandas",
        "--exclude-module=sklearn",
        "--exclude-module=torch",
        
        # Handle wxPython deprecation warning
        "--hidden-import=wx.lib.pubsub.setupkwargs",
        "--hidden-import=wx.lib.pubsub.core",
        "--hidden-import=wx.lib.pubsub.core.arg1",
        "--hidden-import=wx.lib.pubsub.core.kwargs",
        "--hidden-import=wx.lib.pubsub.utils",
    ]

    # Allow switching to a single EXE if user passes "--onefile"
    if any(a == "--onefile" for a in sys.argv[1:]):
        # Replace --onedir with --onefile
        args = [a for a in args if a != "--onedir"] + ["--onefile"]

    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
