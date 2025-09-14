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

    args = argparse.Namespace(directory=str(tmp_path))
    commands.cmd_trace(args, repo)
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["HLR01 SYS001"]
