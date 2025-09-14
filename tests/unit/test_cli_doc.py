import argparse
from pathlib import Path

from app.cli import commands
from app.core.doc_store import load_document
from app.core.repository import FileRequirementRepository


def test_doc_create_and_list(tmp_path, capsys):
    repo = FileRequirementRepository()

    args = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="System", digits=3, parent=None
    )
    commands.cmd_doc_create(args, repo)
    _ = capsys.readouterr()

    args2 = argparse.Namespace(
        directory=str(tmp_path), prefix="HLR", title="High", digits=2, parent="SYS"
    )
    commands.cmd_doc_create(args2, repo)
    _ = capsys.readouterr()

    list_args = argparse.Namespace(directory=str(tmp_path))
    commands.cmd_doc_list(list_args, repo)
    out = capsys.readouterr().out.splitlines()

    assert out == ["HLR High", "SYS System"]

    doc_sys = load_document(Path(tmp_path) / "SYS")
    assert doc_sys.parent is None
    assert doc_sys.digits == 3

    doc_hlr = load_document(Path(tmp_path) / "HLR")
    assert doc_hlr.parent == "SYS"
    assert doc_hlr.digits == 2


def test_doc_delete_removes_subtree(tmp_path, capsys):
    repo = FileRequirementRepository()

    args = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="System", digits=3, parent=None
    )
    commands.cmd_doc_create(args, repo)
    _ = capsys.readouterr()

    args2 = argparse.Namespace(
        directory=str(tmp_path), prefix="HLR", title="High", digits=2, parent="SYS"
    )
    commands.cmd_doc_create(args2, repo)
    _ = capsys.readouterr()

    args3 = argparse.Namespace(
        directory=str(tmp_path), prefix="LLR", title="Low", digits=2, parent="HLR"
    )
    commands.cmd_doc_create(args3, repo)
    _ = capsys.readouterr()

    del_args = argparse.Namespace(directory=str(tmp_path), prefix="HLR")
    commands.cmd_doc_delete(del_args, repo)
    out = capsys.readouterr().out.splitlines()
    assert out == ["HLR"]
    assert not (Path(tmp_path) / "HLR").exists()
    assert not (Path(tmp_path) / "LLR").exists()

    commands.cmd_doc_delete(del_args, repo)
    out2 = capsys.readouterr().out
    assert out2 == "document not found: HLR\n"


def test_doc_delete_dry_run_lists_subtree(tmp_path, capsys):
    repo = FileRequirementRepository()

    args_sys = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="System", digits=3, parent=None
    )
    commands.cmd_doc_create(args_sys, repo)
    _ = capsys.readouterr()

    args_hlr = argparse.Namespace(
        directory=str(tmp_path), prefix="HLR", title="High", digits=2, parent="SYS"
    )
    commands.cmd_doc_create(args_hlr, repo)
    _ = capsys.readouterr()

    item1 = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="S", text="", labels=None
    )
    commands.cmd_item_add(item1, repo)
    _ = capsys.readouterr()

    item2 = argparse.Namespace(
        directory=str(tmp_path), prefix="HLR", title="H", text="", labels=None
    )
    commands.cmd_item_add(item2, repo)
    _ = capsys.readouterr()

    del_args = argparse.Namespace(directory=str(tmp_path), prefix="SYS", dry_run=True)
    commands.cmd_doc_delete(del_args, repo)
    out = capsys.readouterr().out.splitlines()
    assert out == ["SYS", "HLR", "SYS001", "HLR01"]
    assert (Path(tmp_path) / "SYS").exists()
    assert (Path(tmp_path) / "HLR").exists()


def test_doc_delete_requires_confirmation(tmp_path, capsys):
    repo = FileRequirementRepository()

    args = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="System", digits=3, parent=None
    )
    commands.cmd_doc_create(args, repo)
    _ = capsys.readouterr()

    from app.confirm import set_confirm

    messages: list[str] = []

    def fake_confirm(msg: str) -> bool:
        messages.append(msg)
        return False

    set_confirm(fake_confirm)

    del_args = argparse.Namespace(directory=str(tmp_path), prefix="SYS")
    commands.cmd_doc_delete(del_args, repo)
    out = capsys.readouterr().out.strip()
    assert out == "aborted"
    assert (Path(tmp_path) / "SYS").exists()
    assert messages and "SYS" in messages[0]
