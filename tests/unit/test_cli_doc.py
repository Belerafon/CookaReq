import argparse
from pathlib import Path

from app.cli import commands
from app.core.document_store import load_document


def test_doc_create_and_list(tmp_path, capsys):
    args = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="System", parent=None
    )
    commands.cmd_doc_create(args)
    _ = capsys.readouterr()

    args2 = argparse.Namespace(
        directory=str(tmp_path), prefix="HLR", title="High", parent="SYS"
    )
    commands.cmd_doc_create(args2)
    _ = capsys.readouterr()

    list_args = argparse.Namespace(directory=str(tmp_path))
    commands.cmd_doc_list(list_args)
    out = capsys.readouterr().out.splitlines()

    assert out == ["HLR High", "SYS System"]

    doc_sys = load_document(Path(tmp_path) / "SYS")
    assert doc_sys.parent is None
    assert not hasattr(doc_sys, "digits")

    doc_hlr = load_document(Path(tmp_path) / "HLR")
    assert doc_hlr.parent == "SYS"
    assert not hasattr(doc_hlr, "digits")


def test_doc_delete_removes_subtree(tmp_path, capsys):
    args = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="System", parent=None
    )
    commands.cmd_doc_create(args)
    _ = capsys.readouterr()

    args2 = argparse.Namespace(
        directory=str(tmp_path), prefix="HLR", title="High", parent="SYS"
    )
    commands.cmd_doc_create(args2)
    _ = capsys.readouterr()

    args3 = argparse.Namespace(
        directory=str(tmp_path), prefix="LLR", title="Low", parent="HLR"
    )
    commands.cmd_doc_create(args3)
    _ = capsys.readouterr()

    del_args = argparse.Namespace(directory=str(tmp_path), prefix="HLR")
    commands.cmd_doc_delete(del_args)
    out = capsys.readouterr().out.splitlines()
    assert out == ["HLR"]
    assert not (Path(tmp_path) / "HLR").exists()
    assert not (Path(tmp_path) / "LLR").exists()

    commands.cmd_doc_delete(del_args)
    out2 = capsys.readouterr().out
    assert out2 == "document not found: HLR\n"


def test_doc_delete_dry_run_lists_subtree(tmp_path, capsys):
    args_sys = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="System", parent=None
    )
    commands.cmd_doc_create(args_sys)
    _ = capsys.readouterr()

    args_hlr = argparse.Namespace(
        directory=str(tmp_path), prefix="HLR", title="High", parent="SYS"
    )
    commands.cmd_doc_create(args_hlr)
    _ = capsys.readouterr()

    item1 = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="S", statement="", labels=None
    )
    commands.cmd_item_add(item1)
    _ = capsys.readouterr()

    item2 = argparse.Namespace(
        directory=str(tmp_path), prefix="HLR", title="H", statement="", labels=None
    )
    commands.cmd_item_add(item2)
    _ = capsys.readouterr()

    del_args = argparse.Namespace(directory=str(tmp_path), prefix="SYS", dry_run=True)
    commands.cmd_doc_delete(del_args)
    out = capsys.readouterr().out.splitlines()
    assert out == ["SYS", "HLR", "SYS1", "HLR1"]
    assert (Path(tmp_path) / "SYS").exists()
    assert (Path(tmp_path) / "HLR").exists()


def test_doc_delete_requires_confirmation(tmp_path, capsys):
    args = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="System", parent=None
    )
    commands.cmd_doc_create(args)
    _ = capsys.readouterr()

    from app.confirm import set_confirm

    messages: list[str] = []

    def fake_confirm(msg: str) -> bool:
        messages.append(msg)
        return False

    set_confirm(fake_confirm)

    del_args = argparse.Namespace(directory=str(tmp_path), prefix="SYS")
    commands.cmd_doc_delete(del_args)
    out = capsys.readouterr().out.strip()
    assert out == "aborted"
    assert (Path(tmp_path) / "SYS").exists()
    assert messages and "SYS" in messages[0]
