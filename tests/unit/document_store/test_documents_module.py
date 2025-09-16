import pytest
from pathlib import Path

from app.core.document_store import Document, DocumentLabels, LabelDef
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
        digits=3,
        labels=DocumentLabels(
            allow_freeform=True,
            defs=[LabelDef(key="safety", title="Safety", color="#123456")],
        ),
    )
    hlr_doc = Document(
        prefix="HLR",
        title="High level",
        digits=2,
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
            digits=3,
            labels=DocumentLabels(
                allow_freeform=False,
                defs=[LabelDef(key="safety", title="Safety", color="#123456")],
            ),
        ),
    )
    docs = load_documents(tmp_path)
    assert validate_labels("HLR", ["unknown"], docs) == "unknown label: unknown"
