import argparse
import json
from pathlib import Path

import pytest

from app.cli import commands
from app.core.doc_store import (
    Document,
    DocumentLabels,
    LabelDef,
    save_document,
    load_documents,
    validate_labels,
)


@pytest.mark.unit
def test_item_add_rejects_unknown_label(tmp_path, capsys):
    doc_sys = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "HLR", doc_hlr)
    args = argparse.Namespace(
        directory=str(tmp_path),
        prefix="HLR",
        title="T",
        statement="X",
        labels="unknown",
    )
    commands.cmd_item_add(args)
    out = capsys.readouterr().out
    assert "unknown label: unknown" in out
    items_dir = Path(tmp_path) / "HLR" / "items"
    assert not items_dir.exists() or not any(items_dir.iterdir())


@pytest.mark.unit
def test_item_add_accepts_inherited_label(tmp_path, capsys):
    doc_sys = Document(
        prefix="SYS",
        title="System",
        digits=3,
        labels=DocumentLabels(defs=[LabelDef("ui", "UI")]),
    )
    save_document(tmp_path / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "HLR", doc_hlr)
    args = argparse.Namespace(
        directory=str(tmp_path),
        prefix="HLR",
        title="T",
        statement="X",
        labels="ui",
    )
    commands.cmd_item_add(args)
    out = capsys.readouterr().out.strip()
    assert out == "HLR01"
    path = Path(tmp_path) / "HLR" / "items" / "HLR01.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["labels"] == ["ui"]


@pytest.mark.unit
def test_validate_labels_helper(tmp_path):
    doc_sys = Document(
        prefix="SYS",
        title="System",
        digits=3,
        labels=DocumentLabels(defs=[LabelDef("ui", "UI")]),
    )
    save_document(tmp_path / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "HLR", doc_hlr)
    docs = load_documents(tmp_path)
    assert validate_labels("HLR", ["ui"], docs) is None
    assert validate_labels("HLR", ["bad"], docs) == "unknown label: bad"
