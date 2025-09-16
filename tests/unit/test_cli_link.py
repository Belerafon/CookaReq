import argparse
import json
from pathlib import Path

import pytest

from app.cli import commands
<<<<< codex/remove-redundant-names-in-files
from app.core.document_store import Document, item_path, save_document, save_item
=====
from app.core.document_store import Document, save_document, save_item
from app.core.model import requirement_fingerprint
>>>> main


@pytest.mark.unit
def test_link_add(tmp_path, capsys):
    doc_sys = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "HLR", doc_hlr)

    save_item(tmp_path / "SYS", doc_sys, {"id": 1, "title": "S", "statement": "", "labels": [], "links": []})
    save_item(tmp_path / "HLR", doc_hlr, {"id": 1, "title": "H", "statement": "", "labels": [], "links": []})

    args = argparse.Namespace(
        directory=str(tmp_path), rid="HLR01", parents=["SYS001"], replace=False
    )
    commands.cmd_link(args)
    out = capsys.readouterr().out.strip()
    assert out == "HLR01"

    path = item_path(tmp_path / "HLR", doc_hlr, 1)
    data = json.loads(path.read_text(encoding="utf-8"))
    parent_path = Path(tmp_path) / "SYS" / "items" / "SYS001.json"
    parent_data = json.loads(parent_path.read_text(encoding="utf-8"))
    expected_fp = requirement_fingerprint(parent_data)
    assert data["links"] == [{"rid": "SYS001", "fingerprint": expected_fp}]


@pytest.mark.unit
def test_link_rejects_self_link(tmp_path, capsys):
    doc_sys = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc_sys)

    save_item(
        tmp_path / "SYS",
        doc_sys,
        {"id": 1, "title": "S", "statement": "", "labels": [], "links": []},
    )

    args = argparse.Namespace(
        directory=str(tmp_path), rid="SYS001", parents=["SYS001"], replace=False
    )
    commands.cmd_link(args)
    out = capsys.readouterr().out.strip()
    assert out == "invalid link target: SYS001"

    path = item_path(tmp_path / "SYS", doc_sys, 1)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("links") in (None, [])


@pytest.mark.unit
def test_link_rejects_non_ancestor(tmp_path, capsys):
    doc_sys = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "HLR", doc_hlr)
    doc_llr = Document(prefix="LLR", title="Low", digits=2, parent="HLR")
    save_document(tmp_path / "LLR", doc_llr)

    save_item(tmp_path / "HLR", doc_hlr, {"id": 1, "title": "H", "statement": "", "labels": [], "links": []})
    save_item(tmp_path / "LLR", doc_llr, {"id": 1, "title": "L", "statement": "", "labels": [], "links": []})

    args = argparse.Namespace(
        directory=str(tmp_path), rid="HLR01", parents=["LLR01"], replace=False
    )
    commands.cmd_link(args)
    out = capsys.readouterr().out.strip()
    assert out == "invalid link target: LLR01"

    path = item_path(tmp_path / "HLR", doc_hlr, 1)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("links") in (None, [])
