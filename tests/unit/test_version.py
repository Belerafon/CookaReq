from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import version


def _write_version(path: Path, date: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": date}), encoding="utf-8")


def test_load_version_date_falls_back_to_module_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        version.resources,
        "files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError),
    )
    module_root = tmp_path / "app"
    monkeypatch.setattr(version, "__file__", str(module_root / "version.py"))
    _write_version(module_root / "resources" / "version.json", "2024-06-02")

    assert version.load_version_date() == "2024-06-02"


def test_load_version_date_falls_back_to_meipass_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        version.resources,
        "files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError),
    )
    monkeypatch.setattr(version, "__file__", str(tmp_path / "app" / "version.py"))
    bundle_root = tmp_path / "bundle"
    monkeypatch.setattr(version.sys, "_MEIPASS", str(bundle_root), raising=False)
    _write_version(bundle_root / "app" / "resources" / "version.json", "2024-07-09")

    assert version.load_version_date() == "2024-07-09"
