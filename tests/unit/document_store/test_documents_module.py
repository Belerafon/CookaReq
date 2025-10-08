import pytest
from pathlib import Path

from app.core.document_store import Document, DocumentLabels, LabelDef, ValidationError
from app.core.document_store.documents import (
    collect_label_defs,
    collect_labels,
    is_ancestor,
    load_documents,
    save_document,
    validate_labels,
)

pytestmark = pytest.mark.unit


def test_collect_label_inheritance(tmp_path: Path) -> None:
    sys_doc = Document(
        prefix="SYS",
        title="System",
        labels=DocumentLabels(
            allow_freeform=True,
            defs=[LabelDef(key="safety", title="Safety", color="#123456")],
        ),
    )
    hlr_doc = Document(
        prefix="HLR",
        title="High level",
        parent="SYS",
        labels=DocumentLabels(defs=[LabelDef(key="ux", title="UX")]),
    )

    save_document(tmp_path / "SYS", sys_doc)
    save_document(tmp_path / "HLR", hlr_doc)

    docs = load_documents(tmp_path)
    assert is_ancestor("HLR", "SYS", docs) is True

    defs, allow_freeform = collect_label_defs("HLR", docs)
    assert [d.key for d in defs] == ["safety", "ux"]
    assert defs[0].color == "#123456"
    assert defs[1].color.startswith("#")
    assert allow_freeform is True

    allowed, freeform = collect_labels("HLR", docs)
    assert allowed == {"safety", "ux"}
    assert freeform is True

    assert validate_labels("HLR", ["ux"], docs) is None
    assert validate_labels("HLR", ["unknown"], docs) is None

    save_document(
        tmp_path / "SYS",
        Document(
            prefix="SYS",
            title="System",
            labels=DocumentLabels(
                allow_freeform=False,
                defs=[LabelDef(key="safety", title="Safety", color="#123456")],
            ),
        ),
    )
    docs = load_documents(tmp_path)
    assert validate_labels("HLR", ["unknown"], docs) == "unknown label: unknown"


def test_is_ancestor_includes_self(tmp_path: Path) -> None:
    doc = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", doc)
    docs = load_documents(tmp_path)
    assert is_ancestor("SYS", "SYS", docs) is True


def test_document_labels_roundtrip() -> None:
    labels = DocumentLabels(
        allow_freeform=True,
        defs=[LabelDef(key="safety", title="Safety", color=None)],
    )

    as_mapping = labels.to_mapping()
    assert as_mapping == {
        "allowFreeform": True,
        "defs": [{"key": "safety", "title": "Safety", "color": None}],
    }

    restored = DocumentLabels.from_mapping(as_mapping)
    assert restored == labels


def test_document_labels_from_mapping_validates_entries() -> None:
    with pytest.raises(ValidationError) as excinfo:
        DocumentLabels.from_mapping({"defs": ["invalid"]})

    assert "labels.defs[0]" in str(excinfo.value)


def test_document_from_mapping_roundtrip() -> None:
    raw = {
        "title": "System",
        "parent": "ROOT",
        "labels": {
            "allowFreeform": 1,
            "defs": [
                {
                    "key": "safety",
                    "title": "Safety",
                    "color": "#123456",
                }
            ],
        },
        "attributes": {"owner": "QA"},
    }

    document = Document.from_mapping(prefix="SYS", data=raw)

    assert document.title == "System"
    assert document.parent == "ROOT"
    assert document.labels.allow_freeform is True
    assert document.labels.defs[0].color == "#123456"
    assert document.attributes == {"owner": "QA"}

    assert document.to_mapping() == {
        "title": "System",
        "parent": "ROOT",
        "labels": {
            "allowFreeform": True,
            "defs": [
                {
                    "key": "safety",
                    "title": "Safety",
                    "color": "#123456",
                }
            ],
        },
        "attributes": {"owner": "QA"},
    }


def test_document_from_mapping_validates_parent_type() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Document.from_mapping(prefix="SYS", data={"parent": 123})

    assert "parent must be a string" in str(excinfo.value)
