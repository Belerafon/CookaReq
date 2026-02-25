from __future__ import annotations

from pathlib import Path

import pytest

from app.ui.export_helpers import prepare_export_destination, text_export_encoding

pytestmark = pytest.mark.unit


def test_prepare_export_destination_creates_directory_and_copies_assets(tmp_path: Path) -> None:
    target = tmp_path / "export.html"
    assets_source = tmp_path / "SYS" / "assets"
    assets_source.mkdir(parents=True)
    (assets_source / "diagram.png").write_text("data", encoding="utf-8")

    export_path = prepare_export_destination(target, assets_source=assets_source)

    assert export_path.parent.is_dir()
    copied = export_path.parent / "assets" / "diagram.png"
    assert copied.read_text(encoding="utf-8") == "data"


def test_text_export_encoding_uses_utf8_bom_for_csv_and_tsv(tmp_path: Path) -> None:
    assert text_export_encoding(tmp_path / "report.csv") == "utf-8-sig"
    assert text_export_encoding(tmp_path / "report.tsv") == "utf-8-sig"


def test_text_export_encoding_uses_utf8_for_other_formats(tmp_path: Path) -> None:
    assert text_export_encoding(tmp_path / "report.txt") == "utf-8"
