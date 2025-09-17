import argparse

import pytest

import argparse

import pytest

from app.cli import commands
from app.core.document_store import Document, save_document, save_item


def _prepare(root):
    doc_sys = Document(prefix="SYS", title="System")
    save_document(root / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", parent="SYS")
    save_document(root / "HLR", doc_hlr)
    save_item(root / "SYS", doc_sys, {"id": 1, "title": "S", "statement": "", "labels": [], "links": []})
    save_item(
        root / "HLR",
        doc_hlr,
        {"id": 1, "title": "H", "statement": "", "labels": [], "links": ["SYS1"]},
    )


@pytest.mark.unit
def test_trace_export(tmp_path, capsys):
    args = argparse.Namespace(directory=str(tmp_path), format="plain", output=None)
    _prepare(tmp_path)
    commands.cmd_trace(args)
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["HLR1 SYS1"]


@pytest.mark.unit
def test_trace_export_csv(tmp_path, capsys):
    args = argparse.Namespace(directory=str(tmp_path), format="csv", output=None)
    _prepare(tmp_path)
    commands.cmd_trace(args)
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["child,parent", "HLR1,SYS1"]


@pytest.mark.unit
def test_trace_export_html(tmp_path, capsys):
    args = argparse.Namespace(directory=str(tmp_path), format="html", output=None)
    _prepare(tmp_path)
    commands.cmd_trace(args)
    out = capsys.readouterr().out
    assert "<!DOCTYPE html>" in out
    assert "<style>" in out
    assert "<tr><td>HLR1</td><td>SYS1</td></tr>" in out


@pytest.mark.unit
def test_trace_output_file(tmp_path, capsys):
    out_file = tmp_path / "trace.html"
    args = argparse.Namespace(directory=str(tmp_path), format="html", output=str(out_file))
    _prepare(tmp_path)
    commands.cmd_trace(args)
    captured = capsys.readouterr()
    assert captured.out == ""
    data = out_file.read_text()
    assert "<style>" in data
    assert "<tr><td>HLR1</td><td>SYS1</td></tr>" in data


@pytest.mark.unit
def test_trace_output_creates_parent_dirs(tmp_path, capsys):
    out_file = tmp_path / "nested" / "dir" / "trace.csv"
    args = argparse.Namespace(directory=str(tmp_path), format="csv", output=str(out_file))
    _prepare(tmp_path)
    commands.cmd_trace(args)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert out_file.exists()
    data = out_file.read_text().splitlines()
    assert data[0] == "child,parent"
    assert data[1] == "HLR1,SYS1"
