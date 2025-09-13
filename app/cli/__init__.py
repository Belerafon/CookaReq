"""Command-line interface package for CookaReq.

To keep backwards compatibility after switching from ``app/cli.py`` to the
package layout, the function :func:`main` is exposed via attribute access
(``from app.cli import main``).  The actual implementation lives in the
submodule :mod:`app.cli.main` and is imported lazily to avoid shadowing that
module when importing ``app.cli.main`` directly.
"""

from importlib import import_module
from typing import Any


def __getattr__(name: str) -> Any:
    if name == "main":
        return import_module(".main", __name__).main
    raise AttributeError(f"module {__name__!r} has no attribute {name}")


__all__ = ["main"]

