import pytest

from app.application import ApplicationContext
from app.config import ConfigManager
from app.core.document_store import Document, save_document
from app.settings import MCPSettings
from app.ui.main_frame import MainFrame
from app.ui.requirement_model import RequirementModel

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
