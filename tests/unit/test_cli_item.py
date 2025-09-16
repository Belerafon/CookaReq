import argparse
import json
from pathlib import Path

import pytest

from app.cli import commands
from app.core.document_store import Document, DocumentLabels, save_document
from app.core.model import Priority, RequirementType, Status, Verification


@pytest.mark.unit
def test_item_add_and_move(tmp_path, capsys):
    doc_sys = Document(
        prefix="SYS", title="System", digits=3, labels=DocumentLabels(allow_freeform=True)
    )
    save_document(tmp_path / "SYS", doc_sys)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "HLR", doc_hlr)

    add_args = argparse.Namespace(
        directory=str(tmp_path),
        prefix="SYS",
        title="Login",
        statement="User shall login",
        labels=None,
    )
    commands.cmd_item_add(add_args)
    rid = capsys.readouterr().out.strip()
    assert rid == "SYS001"

    path = Path(tmp_path) / "SYS" / "items" / "SYS001.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["title"] == "Login"
    assert data["statement"] == "User shall login"

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
def test_item_move_merges_sources(tmp_path, capsys):
    doc_sys = Document(
        prefix="SYS", title="System", digits=3, labels=DocumentLabels(allow_freeform=True)
    )
    doc_hlr = Document(
        prefix="HLR",
        title="High",
        digits=2,
        parent="SYS",
        labels=DocumentLabels(allow_freeform=True),
    )
    save_document(tmp_path / "SYS", doc_sys)
    save_document(tmp_path / "HLR", doc_hlr)

    add_base = {
        "statement": "Existing statement",
        "type": RequirementType.CONSTRAINT.value,
        "status": Status.IN_REVIEW.value,
        "owner": "Existing owner",
        "priority": Priority.HIGH.value,
        "source": "Existing source",
        "verification": Verification.DEMONSTRATION.value,
        "acceptance": "Existing acceptance",
        "conditions": "Existing conditions",
        "rationale": "Existing rationale",
        "assumptions": "Existing assumptions",
        "modified_at": "2024-03-01T00:00:00Z",
        "labels": ["seed"],
        "attachments": [{"path": "seed.txt", "note": "seed"}],
        "approved_at": "2024-03-02T00:00:00Z",
        "notes": "Existing notes",
        "links": [],
        "revision": 3,
    }
    add_base_path = tmp_path / "seed.json"
    add_base_path.write_text(json.dumps(add_base), encoding="utf-8")

    add_args = argparse.Namespace(
        directory=str(tmp_path),
        prefix="SYS",
        data=str(add_base_path),
        title="Seed title",
        labels=None,
    )
    commands.cmd_item_add(add_args)
    rid = capsys.readouterr().out.strip()
    assert rid == "SYS001"

    parent_args = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="Parent1", statement="", labels=None
    )
    commands.cmd_item_add(parent_args)
    capsys.readouterr()
    parent_args2 = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="Parent2", statement="", labels=None
    )
    commands.cmd_item_add(parent_args2)
    capsys.readouterr()

    move_template = {
        "statement": "Template statement",
        "priority": Priority.LOW.value,
        "attachments": [{"path": "template.txt", "note": "tpl"}],
        "labels": ["template"],
        "notes": "Template notes",
        "links": ["SYS002", "SYS050"],
        "revision": 7,
    }
    move_template_path = tmp_path / "move.json"
    move_template_path.write_text(json.dumps(move_template), encoding="utf-8")

    move_args = argparse.Namespace(
        directory=str(tmp_path),
        rid=rid,
        new_prefix="HLR",
        data=str(move_template_path),
        title="Moved title",
        owner="CLI owner",
        labels="cli, label",
        attachments=json.dumps([{"path": "cli.txt", "note": "cli"}]),
        links="SYS002,SYS003",
        acceptance="",
    )
    commands.cmd_item_move(move_args)
    rid_new = capsys.readouterr().out.strip()
    assert rid_new == "HLR01"

    old_path = Path(tmp_path) / "SYS" / "items" / "SYS001.json"
    new_path = Path(tmp_path) / "HLR" / "items" / "HLR01.json"
    assert not old_path.exists()
    data_new = json.loads(new_path.read_text(encoding="utf-8"))

    assert data_new["title"] == "Moved title"
    assert data_new["statement"] == "Template statement"
    assert data_new["type"] == RequirementType.CONSTRAINT.value
    assert data_new["status"] == Status.IN_REVIEW.value
    assert data_new["owner"] == "CLI owner"
    assert data_new["priority"] == Priority.LOW.value
    assert data_new["source"] == "Existing source"
    assert data_new["verification"] == Verification.DEMONSTRATION.value
    assert data_new["acceptance"] == ""
    assert data_new["conditions"] == "Existing conditions"
    assert data_new["rationale"] == "Existing rationale"
    assert data_new["assumptions"] == "Existing assumptions"
    assert data_new["modified_at"] == "2024-03-01 00:00:00"
    assert data_new["labels"] == ["cli", "label"]
    assert data_new["attachments"] == [{"path": "cli.txt", "note": "cli"}]
    assert data_new["approved_at"] == "2024-03-02 00:00:00"
    assert data_new["notes"] == "Template notes"
    assert data_new["links"] == ["SYS002", "SYS003"]
    assert data_new["revision"] == 7


@pytest.mark.unit
def test_item_move_rejects_invalid_status(tmp_path, capsys):
    doc_sys = Document(prefix="SYS", title="System", digits=3, labels=DocumentLabels())
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "SYS", doc_sys)
    save_document(tmp_path / "HLR", doc_hlr)

    add_args = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="Seed", statement="Body", labels=None
    )
    commands.cmd_item_add(add_args)
    rid = capsys.readouterr().out.strip()

    move_args = argparse.Namespace(
        directory=str(tmp_path), rid=rid, new_prefix="HLR", status="wrong"
    )
    commands.cmd_item_move(move_args)
    out = capsys.readouterr().out
    assert "unknown status" in out

    old_path = Path(tmp_path) / "SYS" / "items" / f"{rid}.json"
    new_path = Path(tmp_path) / "HLR" / "items"
    assert old_path.is_file()
    assert not any(new_path.glob("*.json"))

@pytest.mark.unit
def test_item_add_merges_base_and_arguments(tmp_path, capsys):
    doc_sys = Document(
        prefix="SYS", title="System", digits=3, labels=DocumentLabels(allow_freeform=True)
    )
    doc_hlr = Document(
        prefix="HLR",
        title="High level",
        digits=2,
        parent="SYS",
        labels=DocumentLabels(allow_freeform=True),
    )
    save_document(tmp_path / "SYS", doc_sys)
    save_document(tmp_path / "HLR", doc_hlr)

    seed_args = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="Seed1", statement="S1", labels=None
    )
    commands.cmd_item_add(seed_args)
    capsys.readouterr()
    seed_args2 = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="Seed2", statement="S2", labels=None
    )
    commands.cmd_item_add(seed_args2)
    capsys.readouterr()

    base_data = {
        "title": "Base title",
        "statement": "Base statement",
        "type": RequirementType.CONSTRAINT.value,
        "status": Status.APPROVED.value,
        "owner": "Base owner",
        "priority": Priority.LOW.value,
        "source": "Base source",
        "verification": Verification.TEST.value,
        "acceptance": "Base acceptance",
        "conditions": "Base conditions",
        "rationale": "Base rationale",
        "assumptions": "Base assumptions",
        "modified_at": "2024-01-01T00:00:00Z",
        "labels": ["base"],
        "attachments": [{"path": "base.txt"}],
        "approved_at": "2024-02-01T00:00:00Z",
        "notes": "Base notes",
        "links": ["SYS001"],
        "revision": 5,
    }
    base_path = tmp_path / "payload.json"
    base_path.write_text(json.dumps(base_data), encoding="utf-8")

    args = argparse.Namespace(
        directory=str(tmp_path),
        prefix="HLR",
        data=str(base_path),
        title="Override title",
        type=RequirementType.INTERFACE.value,
        labels="cli, labels",
        links="SYS001,SYS002",
        attachments='[{"path": "cli.txt", "note": "n"}]',
        acceptance="",
    )
    commands.cmd_item_add(args)
    rid = capsys.readouterr().out.strip()
    assert rid == "HLR01"

    item_path = Path(tmp_path) / "HLR" / "items" / "HLR01.json"
    data = json.loads(item_path.read_text(encoding="utf-8"))
    assert data["title"] == "Override title"
    assert data["statement"] == "Base statement"
    assert data["type"] == RequirementType.INTERFACE.value
    assert data["status"] == Status.APPROVED.value
    assert data["owner"] == "Base owner"
    assert data["priority"] == Priority.LOW.value
    assert data["source"] == "Base source"
    assert data["verification"] == Verification.TEST.value
    assert data["acceptance"] == ""
    assert data["conditions"] == "Base conditions"
    assert data["rationale"] == "Base rationale"
    assert data["assumptions"] == "Base assumptions"
    assert data["modified_at"] == "2024-01-01 00:00:00"
    assert data["labels"] == ["cli", "labels"]
    assert data["attachments"] == [{"path": "cli.txt", "note": "n"}]
    assert data["approved_at"] == "2024-02-01 00:00:00"
    assert data["notes"] == "Base notes"
    assert data["links"] == ["SYS001", "SYS002"]
    assert data["revision"] == 5


@pytest.mark.unit
def test_item_add_rejects_invalid_status(tmp_path, capsys):
    doc_sys = Document(prefix="SYS", title="System", digits=3)
    save_document(tmp_path / "SYS", doc_sys)

    args = argparse.Namespace(
        directory=str(tmp_path),
        prefix="SYS",
        title="Invalid",
        statement="Body",
        status="wrong",
        labels=None,
    )
    commands.cmd_item_add(args)
    out = capsys.readouterr().out
    assert "unknown status" in out
    assert not any((tmp_path / "SYS" / "items").glob("*.json"))


@pytest.mark.unit
def test_item_delete_removes_links(tmp_path, capsys):
    doc_sys = Document(prefix="SYS", title="System", digits=3)
    doc_hlr = Document(prefix="HLR", title="High", digits=2, parent="SYS")
    save_document(tmp_path / "SYS", doc_sys)
    save_document(tmp_path / "HLR", doc_hlr)

    add_args = argparse.Namespace(
        directory=str(tmp_path), prefix="SYS", title="S", statement="", labels=None
    )
    commands.cmd_item_add(add_args)
    add_args2 = argparse.Namespace(
        directory=str(tmp_path), prefix="HLR", title="H", statement="", labels=None
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
        directory=str(tmp_path), prefix="SYS", title="S", statement="", labels=None
    )
    commands.cmd_item_add(add_args)
    add_args2 = argparse.Namespace(
        directory=str(tmp_path), prefix="HLR", title="H", statement="", labels=None
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
        directory=str(tmp_path), prefix="SYS", title="S", statement="", labels=None
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

