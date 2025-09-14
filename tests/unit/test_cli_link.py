import argparse
import json
from pathlib import Path

import pytest

from app.cli import commands
from app.core.doc_store import Document, save_document, save_item
from app.core.repository import FileRequirementRepository


@pytest.mark.unit
def test_link_add(tmp_path, capsys):
    repo = FileRequirementRepository()

    doc_sys = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "HLR", doc_hlr)

    save_item(tmp_path / "SYS", doc_sys, {"id": 1, "title": "S", "text": "", "labels": [], "links": []})
    save_item(tmp_path / "HLR", doc_hlr, {"id": 1, "title": "H", "text": "", "labels": [], "links": []})

    args = argparse.Namespace(
        directory=str(tmp_path), rid="HLR01", parents=["SYS001"], replace=False
    )
    commands.cmd_link(args, repo)
    out = capsys.readouterr().out.strip()
    assert out == "HLR01"

    path = Path(tmp_path) / "HLR" / "items" / "HLR01.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["links"] == ["SYS001"]
