import argparse
import os

import pytest

from app.cli import commands
from app.core.document_store import Document, save_document, save_item


@pytest.fixture(scope="session", autouse=True)
def configure_pdf_font_cache(tmp_path_factory):
    cache_dir = tmp_path_factory.mktemp("font-cache")
    previous = os.environ.get("COOKAREQ_FONT_CACHE_DIR")
    os.environ["COOKAREQ_FONT_CACHE_DIR"] = str(cache_dir)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("COOKAREQ_FONT_CACHE_DIR", None)
        else:
            os.environ["COOKAREQ_FONT_CACHE_DIR"] = previous


def _prepare(root):
    doc_sys = Document(prefix="SYS", title="System")
    save_document(root / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High level", parent="SYS")
    save_document(root / "HLR", doc_hlr)
    save_item(
        root / "SYS",
        doc_sys,
        {
            "id": 1,
            "title": "System requirement",
            "statement": "System must operate",
            "labels": ["core"],
            "links": [],
            "status": "approved",
            "owner": "Owner",
            "notes": "System notes",
        },
    )
    save_item(
        root / "HLR",
        doc_hlr,
        {
            "id": 1,
            "title": "High level",
            "statement": "High level statement",
            "labels": [],
            "links": ["SYS1"],
            "status": "draft",
            "assumptions": "Assumption text",
        },
    )


def _prepare_cyrillic(root):
    doc_rus = Document(prefix="RUS", title="Система")
    save_document(root / "RUS", doc_rus)
    save_item(
        root / "RUS",
        doc_rus,
        {
            "id": 1,
            "title": "Требование",
            "statement": "Система должна поддерживать кириллицу",
            "labels": ["локализация"],
            "links": [],
            "status": "draft",
            "notes": "Проверка PDF",
        },
    )


def _make_args(tmp_path, **overrides):
    defaults = {
        "directory": str(tmp_path),
        "documents": [],
        "format": "markdown",
        "output": None,
        "title": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.mark.unit
def test_export_requirements_markdown(tmp_path, capsys):
    _prepare(tmp_path)
    args = _make_args(tmp_path, format="markdown")
    commands.cmd_export_requirements(args)
    data = capsys.readouterr().out
    assert "# Requirements export" in data
    assert "SYS1" in data
    assert "- [SYS1](#SYS1) — System requirement" in data
    assert "Assumption text" in data


@pytest.mark.unit
def test_export_requirements_html(tmp_path, capsys):
    _prepare(tmp_path)
    args = _make_args(tmp_path, format="html", title="Custom title")
    commands.cmd_export_requirements(args)
    html = capsys.readouterr().out
    assert "<!DOCTYPE html>" in html
    assert "Custom title" in html
    assert "<a href='#SYS1'" in html


@pytest.mark.unit
def test_export_requirements_pdf(tmp_path):
    _prepare(tmp_path)
    out_file = tmp_path / "requirements.pdf"
    args = _make_args(tmp_path, format="pdf", output=str(out_file))
    commands.cmd_export_requirements(args)
    data = out_file.read_bytes()
    assert data.startswith(b"%PDF")


@pytest.mark.unit
def test_export_requirements_pdf_cyrillic(tmp_path):
    _prepare_cyrillic(tmp_path)
    out_file = tmp_path / "requirements.pdf"
    args = _make_args(tmp_path, format="pdf", output=str(out_file))
    commands.cmd_export_requirements(args)
    data = out_file.read_bytes()
    assert data.startswith(b"%PDF")
