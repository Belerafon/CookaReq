import pytest
from pathlib import Path

from app.core.document_store import (
    Document,
    DocumentLabels,
    LabelDef,
    RequirementNotFoundError,
    ValidationError,
)
from app.core.document_store.documents import get_document_revision, load_documents, save_document
from app.core.document_store.items import (
    create_requirement,
    delete_requirement,
    get_requirement,
    item_path,
    move_requirement,
    parse_rid,
    rid_for,
    set_requirement_attachments,
    set_requirement_labels,
    set_requirement_links,
    update_requirement_field,
)
from app.core.markdown_utils import MAX_STATEMENT_LENGTH
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
    with pytest.raises(ValidationError):
        create_requirement(
            tmp_path,
            prefix="SYS",
            data={**_base_payload(), "labels": None},
            docs=docs,
        )

    created = create_requirement(
        tmp_path,
        prefix="SYS",
        data={**_base_payload(), "labels": ["safety"]},
        docs=docs,
    )
    assert get_document_revision(load_documents(tmp_path)["SYS"]) == 2
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
    assert get_document_revision(load_documents(tmp_path)["SYS"]) == 3

    relabeled = set_requirement_labels(
        tmp_path,
        created.rid,
        labels=[],
        docs=docs,
    )
    assert relabeled.labels == []
    assert relabeled.revision == updated.revision

    status_updated = update_requirement_field(
        tmp_path,
        created.rid,
        field="status",
        value="approved",
        docs=docs,
    )
    assert status_updated.status.value == "approved"
    assert status_updated.revision == relabeled.revision
    assert get_document_revision(load_documents(tmp_path)["SYS"]) == 3

    fetched = get_requirement(tmp_path, created.rid, docs=docs)
    assert fetched.statement == "Updated"
    assert fetched.labels == []

    with pytest.raises(ValidationError):
        set_requirement_labels(
            tmp_path,
            created.rid,
            labels=None,  # type: ignore[arg-type]
            docs=docs,
        )

    deleted = delete_requirement(
        tmp_path,
        created.rid,
        docs=docs,
    )
    assert deleted == created.rid
    assert not item_path(tmp_path / "SYS", _document, 1).exists()
    assert get_document_revision(load_documents(tmp_path)["SYS"]) == 4


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
            value="Pending approval",
            docs=docs,
        )

    message = str(exc.value)
    assert "invalid status" in message
    assert "draft" in message


def test_create_requirement_rejects_invalid_markdown_table(
    tmp_path: Path, _document: Document
) -> None:
    docs = load_documents(tmp_path)
    payload = _base_payload()
    payload["statement"] = "| A | B |\n|---|---|\n| 1 |"
    with pytest.raises(ValidationError, match="table row"):
        create_requirement(
            tmp_path,
            prefix="SYS",
            data=payload,
            docs=docs,
        )


def test_update_requirement_rejects_disallowed_html(
    tmp_path: Path, _document: Document
) -> None:
    docs = load_documents(tmp_path)
    created = create_requirement(
        tmp_path,
        prefix="SYS",
        data=_base_payload(),
        docs=docs,
    )
    with pytest.raises(ValidationError, match="HTML tag"):
        update_requirement_field(
            tmp_path,
            created.rid,
            field="statement",
            value="Look <script>alert(1)</script>",
            docs=docs,
        )


def test_statement_length_limit(tmp_path: Path, _document: Document) -> None:
    docs = load_documents(tmp_path)
    payload = _base_payload()
    payload["statement"] = "x" * (MAX_STATEMENT_LENGTH + 1)
    with pytest.raises(ValidationError, match="maximum length"):
        create_requirement(
            tmp_path,
            prefix="SYS",
            data=payload,
            docs=docs,
        )


def test_set_attachments_and_links_reject_none(
    tmp_path: Path, _document: Document
) -> None:
    docs = load_documents(tmp_path)
    created = create_requirement(
        tmp_path,
        prefix="SYS",
        data=_base_payload(),
        docs=docs,
    )

    with pytest.raises(ValidationError):
        set_requirement_attachments(
            tmp_path,
            created.rid,
            attachments=None,  # type: ignore[arg-type]
            docs=docs,
        )

    with pytest.raises(ValidationError):
        set_requirement_links(
            tmp_path,
            created.rid,
            links=None,  # type: ignore[arg-type]
            docs=docs,
        )


def test_create_requirement_accepts_attachment_metadata(
    tmp_path: Path, _document: Document
) -> None:
    docs = load_documents(tmp_path)

    created = create_requirement(
        tmp_path,
        prefix="SYS",
        data={
            **_base_payload(),
            "attachments": [{"id": "att-1", "path": "assets/diagram.png", "note": "ref"}],
        },
        docs=docs,
    )

    assert created.attachments[0].id == "att-1"
    assert created.attachments[0].path == "assets/diagram.png"
    assert created.attachments[0].note == "ref"


def test_set_requirement_attachments_rejects_duplicate_ids(
    tmp_path: Path, _document: Document
) -> None:
    docs = load_documents(tmp_path)
    created = create_requirement(
        tmp_path,
        prefix="SYS",
        data=_base_payload(),
        docs=docs,
    )

    with pytest.raises(ValidationError):
        set_requirement_attachments(
            tmp_path,
            created.rid,
            attachments=[
                {"id": "dup", "path": "assets/a.png"},
                {"id": "dup", "path": "assets/b.png"},
            ],
            docs=docs,
        )


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

    docs_after = load_documents(tmp_path)
    assert get_document_revision(docs_after["SYS"]) == 3
    assert get_document_revision(docs_after["HLR"]) == 2

    assert moved.rid == "HLR1"
    assert moved.revision == parent.revision
    assert not item_path(tmp_path / "SYS", sys_doc, parent.id).exists()
    assert item_path(tmp_path / "HLR", hlr_doc, moved.id).is_file()

    updated_child = get_requirement(tmp_path, child.rid, docs=docs)
    assert [link.rid for link in updated_child.links] == [moved.rid]
    assert all(not link.suspect for link in updated_child.links)
    assert updated_child.links[0].fingerprint == requirement_fingerprint(moved)
