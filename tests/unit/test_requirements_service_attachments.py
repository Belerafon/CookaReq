from pathlib import Path

import pytest

from app.core.document_store import Document, DocumentLabels
from app.core.document_store.documents import save_document
from app.services.requirements import (
    MAX_REQUIREMENT_ATTACHMENT_BYTES,
    MAX_SHARED_ARTIFACT_BYTES,
    RequirementsService,
    ValidationError,
)

pytestmark = pytest.mark.unit


def test_upload_requirement_attachment_rejects_large_file(tmp_path: Path) -> None:
    document = Document(
        prefix="SYS",
        title="System",
        labels=DocumentLabels(allow_freeform=True),
    )
    save_document(tmp_path / "SYS", document)
    service = RequirementsService(tmp_path)
    oversized = tmp_path / "oversized.bin"
    oversized.write_bytes(b"0" * (MAX_REQUIREMENT_ATTACHMENT_BYTES + 1))

    with pytest.raises(ValidationError, match="attachment size exceeds limit"):
        service.upload_requirement_attachment("SYS", oversized)


def test_upload_shared_artifact_registers_metadata(tmp_path: Path) -> None:
    document = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", document)
    service = RequirementsService(tmp_path)
    source = tmp_path / "tz.pdf"
    source.write_bytes(b"tz")

    artifact = service.upload_shared_artifact(
        "SYS",
        source,
        kind="tz",
        title="Main TZ",
        note="contract",
        tags=["project", "baseline"],
    )

    assert artifact.kind == "tz"
    assert artifact.title == "Main TZ"
    assert (tmp_path / "SYS" / artifact.path).is_file()
    saved = service.get_document("SYS")
    assert len(saved.shared_artifacts) == 1
    assert saved.shared_artifacts[0].id == artifact.id


def test_upload_shared_artifact_rejects_large_file(tmp_path: Path) -> None:
    document = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", document)
    service = RequirementsService(tmp_path)
    oversized = tmp_path / "oversized-shared.bin"
    oversized.write_bytes(b"0" * (MAX_SHARED_ARTIFACT_BYTES + 1))

    with pytest.raises(ValidationError, match="shared artifact size exceeds limit"):
        service.upload_shared_artifact(
            "SYS",
            oversized,
            kind="general",
            title="Big",
        )


def test_remove_shared_artifact_can_delete_file(tmp_path: Path) -> None:
    document = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", document)
    service = RequirementsService(tmp_path)
    source = tmp_path / "pssa.xlsx"
    source.write_bytes(b"calc")
    artifact = service.upload_shared_artifact(
        "SYS",
        source,
        kind="pssa",
        title="PSSA",
    )

    removed = service.remove_shared_artifact("SYS", artifact.id, delete_file=True)

    assert removed is True
    assert not (tmp_path / "SYS" / artifact.path).exists()
    assert service.get_document("SYS").shared_artifacts == []


def test_update_shared_artifact_changes_metadata(tmp_path: Path) -> None:
    document = Document(prefix="SYS", title="System")
    save_document(tmp_path / "SYS", document)
    service = RequirementsService(tmp_path)
    source = tmp_path / "overview.md"
    source.write_text("overview", encoding="utf-8")
    artifact = service.upload_shared_artifact(
        "SYS",
        source,
        kind="general",
        title="Overview",
        note="v1",
        tags=["doc"],
    )

    updated = service.update_shared_artifact(
        "SYS",
        artifact.id,
        kind="system_overview",
        title="System Overview",
        note="v2",
        include_in_export=False,
        tags=["core", "architecture"],
    )

    assert updated.kind == "system_overview"
    assert updated.title == "System Overview"
    assert updated.note == "v2"
    assert updated.include_in_export is False
    assert updated.tags == ["core", "architecture"]
