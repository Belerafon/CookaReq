"""GUI checks for editor availability based on requirement selection."""

from __future__ import annotations

import pytest

from app.config import ConfigManager
from app.settings import MCPSettings
from app.core.model import Priority, Requirement, RequirementType, Status, Verification
from app.ui.main_frame import MainFrame

wx = pytest.importorskip("wx")

pytestmark = pytest.mark.gui


def _requirement(req_id: int = 1) -> Requirement:
    return Requirement(
        id=req_id,
        title="Title",
        statement="Statement",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="",
        priority=Priority.MEDIUM,
        source="",
        verification=Verification.NOT_DEFINED,
    )


@pytest.mark.gui_smoke
def test_editor_controls_disabled_without_selection(wx_app, gui_context, tmp_path):
    config = ConfigManager(path=tmp_path / "editor-selection.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))
    frame = MainFrame(None, context=gui_context, config=config)
    try:
        assert frame.editor.save_btn.IsEnabled() is False
        assert frame.editor.cancel_btn.IsEnabled() is False

        frame.editor.load(_requirement())
        assert frame.editor.save_btn.IsEnabled() is True
        assert frame.editor.cancel_btn.IsEnabled() is True

        frame._clear_editor_panel()
        assert frame.editor.save_btn.IsEnabled() is False
        assert frame.editor.cancel_btn.IsEnabled() is False
    finally:
        frame.Destroy()
        wx_app.Yield()
