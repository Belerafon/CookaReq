import argparse

import pytest

from app.cli import commands
from app.core.doc_store import Document, save_document, save_item
from app.core.repository import FileRequirementRepository


@pytest.mark.unit
def test_trace_export(tmp_path, capsys):
    repo = FileRequirementRepository()

    doc_sys = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "HLR", doc_hlr)

    save_item(tmp_path / "SYS", doc_sys, {"id": 1, "title": "S", "text": "", "labels": [], "links": []})
    save_item(
        tmp_path / "HLR",
        doc_hlr,
        {"id": 1, "title": "H", "text": "", "labels": [], "links": ["SYS001"]},
    )

    args = argparse.Namespace(directory=str(tmp_path), format="plain", output=None)
    commands.cmd_trace(args, repo)
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["HLR01 SYS001"]


@pytest.mark.unit
def test_trace_export_csv(tmp_path, capsys):
    repo = FileRequirementRepository()

    doc_sys = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "HLR", doc_hlr)

    save_item(tmp_path / "SYS", doc_sys, {"id": 1, "title": "S", "text": "", "labels": [], "links": []})
    save_item(
        tmp_path / "HLR",
        doc_hlr,
        {"id": 1, "title": "H", "text": "", "labels": [], "links": ["SYS001"]},
    )

    args = argparse.Namespace(directory=str(tmp_path), format="csv", output=None)
    commands.cmd_trace(args, repo)
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["child,parent", "HLR01,SYS001"]


@pytest.mark.unit
def test_trace_export_html(tmp_path, capsys):
    repo = FileRequirementRepository()

    doc_sys = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "HLR", doc_hlr)

    save_item(tmp_path / "SYS", doc_sys, {"id": 1, "title": "S", "text": "", "labels": [], "links": []})
    save_item(
        tmp_path / "HLR",
        doc_hlr,
        {"id": 1, "title": "H", "text": "", "labels": [], "links": ["SYS001"]},
    )

    args = argparse.Namespace(directory=str(tmp_path), format="html", output=None)
    commands.cmd_trace(args, repo)
    out = capsys.readouterr().out
    assert "<!DOCTYPE html>" in out
    assert "<style>" in out
    assert "<tr><td>HLR01</td><td>SYS001</td></tr>" in out


@pytest.mark.unit
def test_trace_output_file(tmp_path, capsys):
    repo = FileRequirementRepository()

    doc_sys = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "HLR", doc_hlr)

    save_item(tmp_path / "SYS", doc_sys, {"id": 1, "title": "S", "text": "", "labels": [], "links": []})
    save_item(
        tmp_path / "HLR",
        doc_hlr,
        {"id": 1, "title": "H", "text": "", "labels": [], "links": ["SYS001"]},
    )

    out_file = tmp_path / "trace.html"
    args = argparse.Namespace(directory=str(tmp_path), format="html", output=str(out_file))
    commands.cmd_trace(args, repo)
    captured = capsys.readouterr()
    assert captured.out == ""
    data = out_file.read_text()
    assert "<style>" in data
    assert "<tr><td>HLR01</td><td>SYS001</td></tr>" in data
