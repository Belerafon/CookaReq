import pytest
from pathlib import Path

from app.core.document_store import (
    Document,
    DocumentLabels,
    LabelDef,
    RequirementNotFoundError,
    ValidationError,
)
from app.core.document_store.documents import load_documents, save_document
from app.core.document_store.items import (
    create_requirement,
    delete_requirement,
    get_requirement,
    item_path,
    move_requirement,
    parse_rid,
    rid_for,
    set_requirement_labels,
    update_requirement_field,
)
from app.core.model import requirement_fingerprint

pytestmark = pytest.mark.unit


@pytest.fixture()
def _document(tmp_path: Path) -> Document:
    doc = Document(
        prefix="SYS",
        title="System",
        labels=DocumentLabels(defs=[LabelDef(key="safety", title="Safety")]),
    )
    save_document(tmp_path / "SYS", doc)
    return doc


def _base_payload() -> dict[str, str]:
    return {
        "title": "Title",
        "statement": "Body",
        "type": "requirement",
        "status": "draft",
        "owner": "owner",
        "priority": "medium",
        "source": "source",
        "verification": "analysis",
    }


def test_create_update_and_delete_requirement(
    tmp_path: Path, _document: Document
) -> None:
    docs = load_documents(tmp_path)

    with pytest.raises(ValidationError):
        create_requirement(
            tmp_path,
            prefix="SYS",
            data={**_base_payload(), "labels": "oops"},
            docs=docs,
        )

    created = create_requirement(
        tmp_path,
        prefix="SYS",
        data={**_base_payload(), "labels": ["safety"]},
        docs=docs,
    )
    assert created.rid == rid_for(_document, 1)
    assert parse_rid(created.rid) == ("SYS", 1)

    updated = update_requirement_field(
        tmp_path,
        created.rid,
        field="statement",
        value="Updated",
        docs=docs,
    )
    assert updated.statement == "Updated"
    assert updated.revision == created.revision + 1

    relabeled = set_requirement_labels(
        tmp_path,
        created.rid,
        labels=[],
        docs=docs,
    )
    assert relabeled.labels == []
    assert relabeled.revision == updated.revision + 1

    fetched = get_requirement(tmp_path, created.rid, docs=docs)
    assert fetched.statement == "Updated"
    assert fetched.labels == []

    deleted = delete_requirement(
        tmp_path,
        created.rid,
        docs=docs,
    )
    assert deleted == created.rid
    assert not item_path(tmp_path / "SYS", _document, 1).exists()


def test_update_rejects_mismatched_case_rid(
    tmp_path: Path, _document: Document
) -> None:
    docs = load_documents(tmp_path)

    created = create_requirement(
        tmp_path,
        prefix="SYS",
        data=_base_payload(),
        docs=docs,
    )

    with pytest.raises(RequirementNotFoundError) as exc:
        update_requirement_field(
            tmp_path,
            created.rid.lower(),
            field="status",
            value="approved",
            docs=docs,
        )

    assert created.rid.lower() in str(exc.value)


def test_update_requirement_field_rejects_unknown_status(
    tmp_path: Path, _document: Document
) -> None:
    docs = load_documents(tmp_path)

    created = create_requirement(
        tmp_path,
        prefix="SYS",
        data=_base_payload(),
        docs=docs,
    )

    with pytest.raises(ValidationError) as exc:
        update_requirement_field(
            tmp_path,
            created.rid,
            field="status",
            value="На утверждении",
            docs=docs,
        )

    message = str(exc.value)
    assert "invalid status" in message
    assert "draft" in message


def test_move_requirement_updates_links(tmp_path: Path) -> None:
    sys_doc = Document(
        prefix="SYS",
        title="System",
        labels=DocumentLabels(allow_freeform=True),
    )
    hlr_doc = Document(
        prefix="HLR",
        title="High level",
        parent="SYS",
        labels=DocumentLabels(allow_freeform=True),
    )
    llr_doc = Document(
        prefix="LLR",
        title="Low level",
        parent="HLR",
        labels=DocumentLabels(allow_freeform=True),
    )
    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)
    save_document(tmp_path / "LLR", llr_doc)

    docs = load_documents(tmp_path)

    parent = create_requirement(tmp_path, prefix="SYS", data=_base_payload(), docs=docs)
    child = create_requirement(
        tmp_path,
        prefix="LLR",
        data={**_base_payload(), "title": "Child", "links": [parent.rid]},
        docs=docs,
    )

    moved = move_requirement(
        tmp_path,
        parent.rid,
        new_prefix="HLR",
        docs=docs,
    )

    assert moved.rid == "HLR1"
    assert moved.revision == parent.revision
    assert not item_path(tmp_path / "SYS", sys_doc, parent.id).exists()
    assert item_path(tmp_path / "HLR", hlr_doc, moved.id).is_file()

    updated_child = get_requirement(tmp_path, child.rid, docs=docs)
    assert [link.rid for link in updated_child.links] == [moved.rid]
    assert all(not link.suspect for link in updated_child.links)
    assert updated_child.links[0].fingerprint == requirement_fingerprint(moved)
