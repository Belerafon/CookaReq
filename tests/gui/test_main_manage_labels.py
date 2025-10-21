import pytest

from app.application import ApplicationContext
from app.config import ConfigManager
from app.core.document_store import Document, DocumentLabels, LabelDef, save_document
from app.settings import MCPSettings
from app.ui.main_frame import MainFrame
from app.ui.requirement_model import RequirementModel
from app.services.requirements import RequirementsService
from app.core.model import Priority, RequirementType, Status, Verification

wx = pytest.importorskip("wx")

pytestmark = pytest.mark.gui


class _StubMCP:
    """Minimal stand-in for the MCP controller used by the frame."""

    def start(self, *_args, **_kwargs) -> None:  # pragma: no cover - trivial stub
        pass

    def stop(self) -> None:  # pragma: no cover - trivial stub
        pass

    def is_running(self) -> bool:  # pragma: no cover - trivial stub
        return False


def _create_frame(tmp_path):
    config = ConfigManager(path=tmp_path / "labels.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))
    frame = MainFrame(
        None,
        context=ApplicationContext.for_gui(),
        config=config,
        model=RequirementModel(),
        mcp_factory=_StubMCP,
    )
    frame.Show()
    return frame


def test_manage_labels_menu_state_tracks_documents(wx_app, tmp_path):
    frame = _create_frame(tmp_path)
    try:
        wx_app.Yield()
        assert not frame.navigation.is_manage_labels_enabled()

        doc = Document(prefix="REQ", title="Doc")
        save_document(tmp_path / "REQ", doc)

        frame._load_directory(tmp_path)
        wx_app.Yield()

        assert frame.navigation.is_manage_labels_enabled()
    finally:
        if frame and not frame.IsBeingDeleted():
            frame.Destroy()
            wx_app.Yield()


def test_manage_labels_prompts_without_selection(monkeypatch, wx_app, tmp_path):
    frame = _create_frame(tmp_path)
    try:
        wx_app.Yield()
        captured: dict[str, tuple[str, str, int]] = {}

        def fake_message_box(message, caption, style=0):
            captured["call"] = (message, caption, style)
            return wx.OK

        monkeypatch.setattr(wx, "MessageBox", fake_message_box)

        frame.on_manage_labels(wx.CommandEvent())

        assert "call" in captured
        message, caption, style = captured["call"]
        assert "Select requirements folder first" in message
        assert caption == "No Data"
        assert style == 0
    finally:
        if frame and not frame.IsBeingDeleted():
            frame.Destroy()
            wx_app.Yield()


def test_manage_labels_removal_updates_loaded_requirements(monkeypatch, wx_app, tmp_path):
    doc = Document(
        prefix="REQ",
        title="Doc",
        labels=DocumentLabels(defs=[LabelDef("bug", "Bug", None)]),
    )
    save_document(tmp_path / "REQ", doc)
    service = RequirementsService(tmp_path)
    service.create_requirement(
        "REQ",
        {
            "id": 1,
            "title": "First",
            "statement": "Do something",
            "type": RequirementType.REQUIREMENT.value,
            "status": Status.DRAFT.value,
            "owner": "Owner",
            "priority": Priority.MEDIUM.value,
            "source": "Spec",
            "verification": Verification.ANALYSIS.value,
            "labels": ["bug"],
        },
    )

    frame = _create_frame(tmp_path)
    try:
        frame._load_directory(tmp_path)
        wx_app.Yield()
        requirements = frame.model.get_all()
        assert requirements and requirements[0].labels == ["bug"]

        class _DialogStub:
            def __init__(self, _parent, labels):
                self._labels = labels

            def ShowModal(self):
                return wx.ID_OK

            def Destroy(self):
                pass

            def get_labels(self):
                return []

            def get_key_changes(self):
                return {}

            def get_removed_labels(self):
                return {"bug": True}

        monkeypatch.setattr("app.ui.main_frame.documents.LabelsDialog", _DialogStub)

        frame.on_manage_labels(wx.CommandEvent())
        wx_app.Yield()

        updated = frame.model.get_all()
        assert updated and updated[0].labels == []

        list_ctrl = frame.panel.list
        column_count = list_ctrl.GetColumnCount()
        labels_column = None
        for idx in range(column_count):
            column = list_ctrl.GetColumn(idx)
            text = column.GetText() if hasattr(column, "GetText") else ""
            if text.strip().lower() == "labels":
                labels_column = idx
                break
        if labels_column is not None:
            assert list_ctrl.GetItemText(0, labels_column) == ""
    finally:
        if frame and not frame.IsBeingDeleted():
            frame.Destroy()
            wx_app.Yield()
