import argparse

from app.cli import commands
from app.core.document_store import Document, save_document, save_item


def test_item_list_outputs_requirements_with_optional_links(tmp_path, capsys, cli_context):
    doc_sys = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", parent="SYS")
    save_document(tmp_path / "HLR", doc_hlr)

    save_item(
        tmp_path / "SYS",
        doc_sys,
        {
            "id": 1,
            "title": "System Parent",
            "statement": "",
            "labels": [],
            "status": "approved",
            "links": [],
        },
    )
    save_item(
        tmp_path / "HLR",
        doc_hlr,
        {
            "id": 1,
            "title": "Primary",
            "statement": "",
            "labels": ["software"],
            "status": "approved",
            "links": [{"rid": "SYS1", "revision": 1}],
        },
    )
    save_item(
        tmp_path / "HLR",
        doc_hlr,
        {
            "id": 2,
            "title": "Secondary",
            "statement": "",
            "labels": ["hardware"],
            "status": "draft",
            "links": [],
        },
    )

    args = argparse.Namespace(
        directory=str(tmp_path),
        prefix="HLR",
        page=1,
        per_page=50,
        status="approved",
        labels="software",
        show_links=True,
        format="text",
    )

    rc = commands.cmd_item_list(args, cli_context)
    out = capsys.readouterr().out.strip().splitlines()

    assert rc == 0
    assert out == ["HLR1 Primary -> SYS1"]


def test_item_list_fails_for_unknown_document(tmp_path, capsys, cli_context):
    args = argparse.Namespace(
        directory=str(tmp_path),
        prefix="MISSING",
        page=1,
        per_page=50,
        status=None,
        labels=None,
        show_links=False,
        format="text",
    )

    rc = commands.cmd_item_list(args, cli_context)
    out = capsys.readouterr().out

    assert rc == 1
    assert out == "unknown document prefix: MISSING\n"


def test_item_list_json_format(tmp_path, capsys, cli_context):
    doc = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", doc)
    save_item(
        tmp_path / "SYS",
        doc,
        {
            "id": 1,
            "title": "Req",
            "statement": "",
            "labels": ["system"],
            "status": "approved",
            "links": [],
            "context_docs": ["related/ctx.md"],
        },
    )

    args = argparse.Namespace(
        directory=str(tmp_path),
        prefix="SYS",
        page=1,
        per_page=50,
        status=None,
        labels=None,
        show_links=False,
        format="json",
    )

    rc = commands.cmd_item_list(args, cli_context)
    out = capsys.readouterr().out

    assert rc == 0
    assert '"rid": "SYS1"' in out
    assert '"status": "approved"' in out
    assert '"context_docs": [' in out
    assert '"related/ctx.md"' in out
