import argparse
import json
from pathlib import Path

import pytest

from app.cli import commands
from app.core.doc_store import Document, save_document


@pytest.mark.unit
def test_item_add_and_move(tmp_path, capsys):
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
    commands.cmd_item_add(add_args)
    rid = capsys.readouterr().out.strip()
    assert rid == "SYS001"

    path = Path(tmp_path) / "SYS" / "items" / "SYS001.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["title"] == "Login"
    assert data["text"] == "User shall login"

    move_args = argparse.Namespace(
        directory=str(tmp_path), rid="SYS001", new_prefix="HLR"
    )
    commands.cmd_item_move(move_args)
    rid2 = capsys.readouterr().out.strip()
    assert rid2 == "HLR01"

    old_path = Path(tmp_path) / "SYS" / "items" / "SYS001.json"
    new_path = Path(tmp_path) / "HLR" / "items" / "HLR01.json"
    assert not old_path.exists()
    assert new_path.is_file()
    data2 = json.loads(new_path.read_text(encoding="utf-8"))
    assert data2["id"] == 1
    assert data2["title"] == "Login"


@pytest.mark.unit
def test_item_delete_removes_links(tmp_path, capsys):
    doc_sys = Document(prefix="SYS", title="System", digits=3)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "SYS", doc_sys)
    save_document(tmp_path / "HLR", doc_hlr)

    add_args = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="S", text="", labels=None
    )
    commands.cmd_item_add(add_args)
    add_args2 = argparse.Namespace(
        directory=str(tmp_path), prefix="HLR", title="H", text="", labels=None
    )
    commands.cmd_item_add(add_args2)
    # link child to parent
    link_args = argparse.Namespace(
        directory=str(tmp_path), rid="HLR01", parents=["SYS001"], replace=False
    )
    commands.cmd_link(link_args)
    capsys.readouterr()

    del_args = argparse.Namespace(directory=str(tmp_path), rid="SYS001")
    commands.cmd_item_delete(del_args)
    out = capsys.readouterr().out.strip()
    assert out == "SYS001"

    assert not (tmp_path / "SYS" / "items" / "SYS001.json").exists()
    data = json.loads((tmp_path / "HLR" / "items" / "HLR01.json").read_text())
    assert data.get("links") == []


@pytest.mark.unit
def test_item_delete_dry_run_lists_links(tmp_path, capsys):
    doc_sys = Document(prefix="SYS", title="System", digits=3)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "SYS", doc_sys)
    save_document(tmp_path / "HLR", doc_hlr)

    add_args = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="S", text="", labels=None
    )
    commands.cmd_item_add(add_args)
    add_args2 = argparse.Namespace(
        directory=str(tmp_path), prefix="HLR", title="H", text="", labels=None
    )
    commands.cmd_item_add(add_args2)
    link_args = argparse.Namespace(
        directory=str(tmp_path), rid="HLR01", parents=["SYS001"], replace=False
    )
    commands.cmd_link(link_args)
    capsys.readouterr()

    del_args = argparse.Namespace(directory=str(tmp_path), rid="SYS001", dry_run=True)
    commands.cmd_item_delete(del_args)
    out = capsys.readouterr().out.splitlines()
    assert out == ["SYS001", "HLR01"]
    # nothing removed or updated
    assert (tmp_path / "SYS" / "items" / "SYS001.json").exists()
    data = json.loads((tmp_path / "HLR" / "items" / "HLR01.json").read_text())
    assert data.get("links") == ["SYS001"]


def test_item_delete_requires_confirmation(tmp_path, capsys):
    doc_sys = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc_sys)

    add_args = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="S", text="", labels=None
    )
    commands.cmd_item_add(add_args)
    _ = capsys.readouterr()

    from app.confirm import set_confirm

    messages: list[str] = []

    def fake_confirm(msg: str) -> bool:
        messages.append(msg)
        return False

    set_confirm(fake_confirm)

    del_args = argparse.Namespace(directory=str(tmp_path), rid="SYS001")
    commands.cmd_item_delete(del_args)
    out = capsys.readouterr().out.strip()
    assert out == "aborted"
    assert (tmp_path / "SYS" / "items" / "SYS001.json").exists()
    assert messages and "SYS001" in messages[0]

