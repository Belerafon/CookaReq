from pathlib import Path

import pytest

from app.core.document_store import Document, DocumentLabels
from app.core.document_store.documents import save_document
from app.services.requirements import (
    MAX_REQUIREMENT_ATTACHMENT_BYTES,
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
