from __future__ import annotations

from datetime import date
from pathlib import Path
from zipfile import ZipFile

import pytest

from app.core.document_store import Document
from app.core.project_archive import (
    build_project_archive_name,
    create_project_archive,
    resolve_root_document_prefix,
)

pytestmark = pytest.mark.unit


def test_resolve_root_document_prefix_returns_top_ancestor() -> None:
    docs = {
        "SYS": Document(prefix="SYS", title="System"),
        "HLR": Document(prefix="HLR", title="High Level", parent="SYS"),
        "LLR": Document(prefix="LLR", title="Low Level", parent="HLR"),
    }

    assert resolve_root_document_prefix(docs, "LLR") == "SYS"


def test_build_project_archive_name_uses_root_revision_and_date() -> None:
    docs = {
        "SYS": Document(prefix="SYS", title="System", attributes={"doc_revision": 7}),
        "HLR": Document(prefix="HLR", title="High Level", parent="SYS"),
    }
    name = build_project_archive_name(
        project_dir=Path("/tmp/MyProject"),
        docs=docs,
        current_prefix="HLR",
        today=date(2026, 3, 31),
    )

    assert name == "MyProject_rev7_20260331.zip"


def test_build_project_archive_name_strips_previous_archive_suffixes() -> None:
    docs = {
        "SYS": Document(prefix="SYS", title="System", attributes={"doc_revision": 237}),
    }
    name = build_project_archive_name(
        project_dir=Path("/tmp/Требования CookaReq Проект_rev237_20260407"),
        docs=docs,
        current_prefix="SYS",
        today=date(2026, 4, 14),
    )

    assert name == "Требования CookaReq Проект_rev237_20260414.zip"


def test_create_project_archive_includes_documents_and_hidden_internal_folder(
    tmp_path: Path,
) -> None:
    root = tmp_path / "demo"
    (root / "SYS" / "items").mkdir(parents=True)
    (root / ".cookareq").mkdir(parents=True)
    (root / "SYS" / "document.json").write_text('{"title":"SYS"}', encoding="utf-8")
    (root / "SYS" / "items" / "1.json").write_text('{"id":1}', encoding="utf-8")
    (root / ".cookareq" / "state.json").write_text("{}", encoding="utf-8")
    (root / "README.txt").write_text("ok", encoding="utf-8")
    target = tmp_path / "backup.zip"

    files_count = create_project_archive(project_dir=root, output_path=target)

    assert files_count == 4
    with ZipFile(target) as archive:
        members = set(archive.namelist())
    assert "SYS/document.json" in members
    assert "SYS/items/1.json" in members
    assert ".cookareq/state.json" in members
    assert "README.txt" in members
