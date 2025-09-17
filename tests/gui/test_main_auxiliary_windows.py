"""Tests for tracking auxiliary top-level frames in :class:`MainFrame`."""

from __future__ import annotations

import pytest

from app.config import ConfigManager
from app.settings import MCPSettings
from app.ui.main_frame import MainFrame
from app.ui.requirement_model import RequirementModel


pytestmark = pytest.mark.gui


def test_auxiliary_frames_closed_on_shutdown(monkeypatch, wx_app, tmp_path):
    """Ensure graph/matrix frames are tracked, auto-unregistered and closed."""

    wx = pytest.importorskip("wx")

    config = ConfigManager(path=tmp_path / "config.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))
    frame = MainFrame(None, config=config, model=RequirementModel())
    try:
        class _Controller:
            def iter_links(self):
                return [("REQ2", "REQ1")]

        frame.docs_controller = _Controller()
        frame.current_dir = tmp_path

        message_calls: list[tuple] = []

        def _record_message(*args, **kwargs):
            message_calls.append((args, kwargs))
            return wx.ID_OK

        monkeypatch.setattr(wx, "MessageBox", _record_message)

        frame.on_show_derivation_graph(None)
        frame.on_show_trace_matrix(None)
        wx_app.Yield()

        assert len(frame._auxiliary_frames) == 2  # type: ignore[attr-defined]

        created_frames = list(frame._auxiliary_frames)  # type: ignore[attr-defined]
        manual_close = created_frames[0]
        manual_close.Close(True)
        wx_app.Yield()

        assert manual_close not in frame._auxiliary_frames  # type: ignore[attr-defined]

        frame._on_close(None)
        wx_app.Yield()

        assert frame._auxiliary_frames == set()  # type: ignore[attr-defined]
        for wnd in created_frames[1:]:
            assert wnd.IsBeingDeleted() or not wnd.IsShownOnScreen()

        assert message_calls == []
    finally:
        if not frame.IsBeingDeleted():
            frame.Destroy()
        wx_app.Yield()
