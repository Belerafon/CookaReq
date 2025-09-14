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
