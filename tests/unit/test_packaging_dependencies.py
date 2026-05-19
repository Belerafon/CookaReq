from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_wxpython_is_gui_extra_only() -> None:
    data = _pyproject()
    deps = data["project"]["dependencies"]
    optional = data["project"]["optional-dependencies"]

    assert "wxPython" not in deps
    assert "wxPython" in optional["gui"]
