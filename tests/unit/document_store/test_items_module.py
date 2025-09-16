import pytest
from pathlib import Path

from app.core.document_store import (
    Document,
    DocumentLabels,
    LabelDef,
    ValidationError,
)
from app.core.document_store.documents import load_documents, save_document
from app.core.document_store.items import (
    create_requirement,
    delete_requirement,
    get_requirement,
    item_path,
    parse_rid,
    patch_requirement,
    rid_for,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def _document(tmp_path: Path) -> Document:
    doc = Document(
        prefix="SYS",
        title="System",
        digits=3,
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


def test_create_patch_and_delete_requirement(tmp_path: Path, _document: Document) -> None:
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

    patched = patch_requirement(
        tmp_path,
        created.rid,
        [
            {"op": "replace", "path": "/statement", "value": "Updated"},
            {"op": "replace", "path": "/revision", "value": 5},
        ],
        expected_revision=created.revision,
        docs=docs,
    )
    assert patched.statement == "Updated"
    assert patched.revision == 5

    fetched = get_requirement(tmp_path, created.rid, docs=docs)
    assert fetched.statement == "Updated"

    deleted = delete_requirement(
        tmp_path,
        created.rid,
        expected_revision=patched.revision,
        docs=docs,
    )
    assert deleted == created.rid
    assert not item_path(tmp_path / "SYS", _document, 1).exists()
