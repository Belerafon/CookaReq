"""Tests for auxiliary top-level frames managed by :class:`MainFrame`."""

from __future__ import annotations

import types

import pytest

from app.config import ConfigManager
from app.settings import MCPSettings
from app.ui.main_frame import MainFrame
from app.ui.requirement_model import RequirementModel


pytestmark = pytest.mark.gui


def test_auxiliary_frames_closed_on_shutdown(monkeypatch, wx_app, tmp_path, gui_context):
    """Ensure graph/matrix frames close automatically with the main window."""

    wx = pytest.importorskip("wx")

    config = ConfigManager(path=tmp_path / "config.ini")
    config.set_mcp_settings(MCPSettings(auto_start=False))
    frame = MainFrame(
        None,
        context=gui_context,
        config=config,
        model=RequirementModel(),
    )
    try:
        from types import SimpleNamespace

        from app.core.trace_matrix import (
            TraceDirection,
            TraceMatrixAxisConfig,
            TraceMatrixConfig,
        )
        import app.ui.trace_matrix as trace_matrix_module

        class _Controller:
            def __init__(self):
                self.documents = {
                    "REQ": SimpleNamespace(prefix="REQ", title="Doc", parent=None)
                }

            def iter_links(self):
                return [("REQ2", "REQ1")]

            def load_documents(self):
                return self.documents

            def build_trace_matrix(self, config):
                entry = SimpleNamespace(rid="REQ1")
                summary = SimpleNamespace(
                    total_rows=1,
                    total_columns=1,
                    total_pairs=1,
                    linked_pairs=0,
                    link_count=0,
                    row_coverage=0.0,
                    column_coverage=0.0,
                    pair_coverage=0.0,
                    orphan_rows=(),
                    orphan_columns=(),
                )
                return SimpleNamespace(
                    config=config,
                    direction=TraceDirection.CHILD_TO_PARENT,
                    rows=(entry,),
                    columns=(entry,),
                    cells={},
                    summary=summary,
                )

        frame.docs_controller = _Controller()
        frame.current_dir = tmp_path

        message_calls: list[tuple] = []

        def _record_message(*args, **kwargs):
            message_calls.append((args, kwargs))
            return wx.ID_OK

        monkeypatch.setattr(wx, "MessageBox", _record_message)

        class _DialogStub:
            destroyed = False

            def __init__(self, *args, **kwargs):
                self.destroyed = False

            def ShowModal(self):
                return wx.ID_OK

            def get_config(self):
                return TraceMatrixConfig(
                    rows=TraceMatrixAxisConfig(documents=("REQ",)),
                    columns=TraceMatrixAxisConfig(documents=("REQ",)),
                )

            def Destroy(self):
                self.destroyed = True

        class _MatrixFrameStub(wx.Frame):
            def __init__(self, parent, controller, config, matrix):
                super().__init__(parent, title="Trace Matrix Stub")

        monkeypatch.setattr(
            trace_matrix_module,
            "TraceMatrixConfigDialog",
            _DialogStub,
        )
        monkeypatch.setattr(
            trace_matrix_module,
            "TraceMatrixFrame",
            _MatrixFrameStub,
        )

        created_frames: list[wx.Frame] = []
        original_register = frame.register_auxiliary_frame

        def _tracking_register(self, aux_frame: wx.Frame) -> None:
            created_frames.append(aux_frame)
            original_register(aux_frame)

        monkeypatch.setattr(
            frame,
            "register_auxiliary_frame",
            types.MethodType(_tracking_register, frame),
        )

        frame.on_show_derivation_graph(None)
        frame.on_show_trace_matrix(None)
        wx_app.Yield()

        assert len(created_frames) == 2

        destroyed: set[int] = set()

        for idx, aux in enumerate(created_frames):
            def _on_destroy(event: wx.WindowDestroyEvent, marker=idx) -> None:
                destroyed.add(marker)
                event.Skip()

            aux.Bind(wx.EVT_WINDOW_DESTROY, _on_destroy)

        frame._on_close(None)
        wx_app.Yield()

        assert destroyed == {0, 1}
        for aux in created_frames:
            with pytest.raises(RuntimeError):
                aux.IsShownOnScreen()

        assert message_calls == []
    finally:
        if not frame.IsBeingDeleted():
            frame.Destroy()
        wx_app.Yield()
