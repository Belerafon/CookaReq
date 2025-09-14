import argparse
import json
from pathlib import Path

import pytest

from app.cli import commands
from app.core.doc_store import Document, save_document
from app.core.repository import FileRequirementRepository


@pytest.mark.unit
def test_item_add_and_move(tmp_path, capsys):
    repo = FileRequirementRepository()

    doc_sys = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "HLR", doc_hlr)

    add_args = argparse.Namespace(
        directory=str(tmp_path),
        prefix="SYS",
        title="Login",
        text="User shall login",
        labels=None,
    )
    commands.cmd_item_add(add_args, repo)
    rid = capsys.readouterr().out.strip()
    assert rid == "SYS001"

    path = Path(tmp_path) / "SYS" / "items" / "SYS001.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["title"] == "Login"
    assert data["text"] == "User shall login"

    move_args = argparse.Namespace(
        directory=str(tmp_path), rid="SYS001", new_prefix="HLR"
    )
    commands.cmd_item_move(move_args, repo)
    rid2 = capsys.readouterr().out.strip()
    assert rid2 == "HLR01"

    old_path = Path(tmp_path) / "SYS" / "items" / "SYS001.json"
    new_path = Path(tmp_path) / "HLR" / "items" / "HLR01.json"
    assert not old_path.exists()
    assert new_path.is_file()
    data2 = json.loads(new_path.read_text(encoding="utf-8"))
    assert data2["id"] == 1
    assert data2["title"] == "Login"

