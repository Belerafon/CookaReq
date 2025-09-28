import argparse
import json

import pytest

from app.cli import commands
from app.core.document_store import Document, save_document, save_item


def _prepare(root):
    doc_sys = Document(prefix="SYS", title="System")
    save_document(root / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", parent="SYS")
    save_document(root / "HLR", doc_hlr)
    save_item(
        root / "SYS",
        doc_sys,
        {"id": 1, "title": "S", "statement": "", "labels": [], "links": [], "status": "approved"},
    )
    save_item(
        root / "HLR",
        doc_hlr,
        {
            "id": 1,
            "title": "H",
            "statement": "",
            "labels": [],
            "links": ["SYS1"],
            "status": "approved",
        },
    )


def _make_args(tmp_path, **overrides):
    defaults = {
        "directory": str(tmp_path),
        "rows": ["HLR"],
        "columns": ["SYS"],
        "format": "pairs",
        "output": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


@pytest.mark.unit
def test_trace_export(tmp_path, capsys, cli_context):
    args = _make_args(tmp_path, format="pairs")
    _prepare(tmp_path)
    commands.cmd_trace(args, cli_context)
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["HLR1 SYS1"]


@pytest.mark.unit
def test_trace_export_csv(tmp_path, capsys, cli_context):
    args = _make_args(tmp_path, format="matrix-csv")
    _prepare(tmp_path)
    commands.cmd_trace(args, cli_context)
    out = capsys.readouterr().out.strip().splitlines()
    assert out[0] == "RID,Title,Document,Status,SYS1 (System)"
    assert out[1] == "HLR1,H,High,approved,linked"


@pytest.mark.unit
def test_trace_export_html(tmp_path, capsys, cli_context):
    args = _make_args(tmp_path, format="matrix-html")
    _prepare(tmp_path)
    commands.cmd_trace(args, cli_context)
    out = capsys.readouterr().out
    assert "<!DOCTYPE html>" in out
    assert "<style>" in out
    assert "<td class='linked'>linked</td>" in out
    assert "Total rows" in out


@pytest.mark.unit
def test_trace_export_json(tmp_path, capsys, cli_context):
    args = _make_args(tmp_path, format="matrix-json")
    _prepare(tmp_path)
    commands.cmd_trace(args, cli_context)
    data = capsys.readouterr().out
    payload = json.loads(data)
    assert payload["direction"] == "child-to-parent"
    assert payload["rows"][0]["rid"] == "HLR1"
    assert payload["cells"][0]["row"] == "HLR1"
    assert payload["summary"]["linked_pairs"] == 1


@pytest.mark.unit
def test_trace_output_file(tmp_path, capsys, cli_context):
    out_file = tmp_path / "trace.html"
    args = _make_args(tmp_path, format="matrix-html", output=str(out_file))
    _prepare(tmp_path)
    commands.cmd_trace(args, cli_context)
    captured = capsys.readouterr()
    assert captured.out == ""
    data = out_file.read_text()
    assert "<style>" in data
    assert "linked" in data


@pytest.mark.unit
def test_trace_output_creates_parent_dirs(tmp_path, capsys, cli_context):
    out_file = tmp_path / "nested" / "dir" / "trace.csv"
    args = _make_args(tmp_path, format="matrix-csv", output=str(out_file))
    _prepare(tmp_path)
    commands.cmd_trace(args, cli_context)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert out_file.exists()
    data = out_file.read_text().splitlines()
    assert data[0] == "RID,Title,Document,Status,SYS1 (System)"
    assert data[1] == "HLR1,H,High,approved,linked"
