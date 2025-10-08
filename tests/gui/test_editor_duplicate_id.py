import pytest

from pathlib import Path

from app.core.document_store import Document, RequirementIDCollisionError
from app.core.model import (
    Requirement,
    RequirementType,
    Status,
    Priority,
    Verification,
)
from app.services.requirements import RequirementsService
from app.ui.editor_panel import EditorPanel

pytestmark = pytest.mark.gui


def _make_requirement(req_id: int) -> Requirement:
    return Requirement(
        id=req_id,
        title="Existing",
        statement="Statement",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="owner",
        priority=Priority.MEDIUM,
        source="source",
        verification=Verification.ANALYSIS,
    )


def test_editor_save_rejects_duplicate_id(monkeypatch, wx_app, tmp_path: Path) -> None:
    wx = pytest.importorskip("wx")
    doc = Document(prefix="SYS", title="System")
    doc_dir = tmp_path / "SYS"
    service = RequirementsService(tmp_path)
    service.save_document(doc)
    assert doc_dir.exists()
    service.save_requirement_payload("SYS", _make_requirement(1).to_mapping())

    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_service(service)
    panel.set_document("SYS")
    panel.new_requirement()
    panel.fields["id"].ChangeValue("1")
    panel.fields["title"].ChangeValue("Duplicate")
    panel.fields["statement"].ChangeValue("Copy")

    messages: list[str] = []

    import app.ui.editor_panel as editor_module

    def fake_message(message: str, caption: str, style: int = 0) -> int:
        messages.append(message)
        return wx.ID_OK

    monkeypatch.setattr(editor_module.wx, "MessageBox", fake_message)

    with pytest.raises(RequirementIDCollisionError):
        panel.save("SYS")

    assert messages, "duplicate warning should be shown"
    assert "already exists" in messages[0]
    assert panel._id_conflict is True

    panel.Destroy()
    frame.Destroy()
