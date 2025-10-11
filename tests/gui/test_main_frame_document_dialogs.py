from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import wx

from app.config import ConfigManager
from app.ui.requirement_model import RequirementModel
from app.settings import MCPSettings
from app.ui import main_frame as main_frame_module
from app.ui.document_dialog import DocumentProperties
from app.ui.main_frame import MainFrame


pytestmark = pytest.mark.gui


@pytest.fixture
def main_frame(wx_app, tmp_path, gui_context):
    """Provide a ``MainFrame`` instance with MCP auto-start disabled."""

    config_path = tmp_path / "config.ini"
    config = ConfigManager(path=config_path)
    config.set_mcp_settings(MCPSettings(auto_start=False))
    frame = MainFrame(
        None,
        context=gui_context,
        config=config,
        model=RequirementModel(),
    )
    try:
        yield frame
    finally:
        frame.Destroy()
        wx_app.Yield()


def _install_dialog_stub(monkeypatch, results, properties=None):
    """Replace :class:`DocumentPropertiesDialog` with a controllable stub."""

    if properties is None:
        properties = [None] * len(results)
    instances = []

    class _DialogStub:
        def __init__(self, *args, **kwargs):
            index = len(instances)
            if index >= len(results):
                raise AssertionError("more dialogs instantiated than configured")
            self._result = results[index]
            self._properties = properties[index] if index < len(properties) else None
            self.destroyed = False
            self.init_args = args
            self.init_kwargs = kwargs
            instances.append(self)

        def ShowModal(self):
            return self._result

        def get_properties(self):
            return self._properties

        def Destroy(self):
            self.destroyed = True

    monkeypatch.setattr(main_frame_module, "DocumentPropertiesDialog", _DialogStub)
    return instances


@pytest.mark.gui_smoke
def test_on_new_document_cancel_destroys_dialog(main_frame, tmp_path, monkeypatch):
    """Cancellation should still destroy the dialog between invocations."""

    main_frame.docs_controller = object()
    main_frame.current_dir = tmp_path
    main_frame._refresh_documents = Mock()

    dialogs = _install_dialog_stub(
        monkeypatch,
        results=[wx.ID_CANCEL, wx.ID_CANCEL],
    )

    main_frame.on_new_document(parent_prefix=None)
    main_frame.on_new_document(parent_prefix=None)

    assert len(dialogs) == 2
    assert all(dialog.destroyed for dialog in dialogs)
    main_frame._refresh_documents.assert_not_called()


@pytest.mark.gui_smoke
def test_on_new_document_create_uses_controller(main_frame, tmp_path, monkeypatch):
    """Successful creation should call controller, refresh view and destroy dialog."""

    class _Controller:
        def __init__(self):
            self.created = []

        def create_document(self, prefix, title, parent):
            self.created.append((prefix, title, parent))
            return SimpleNamespace(prefix=prefix)

    controller = _Controller()
    main_frame.docs_controller = controller
    main_frame.current_dir = tmp_path
    main_frame._selected_requirement_id = 999
    main_frame._refresh_documents = Mock()

    dialogs = _install_dialog_stub(
        monkeypatch,
        results=[wx.ID_OK],
        properties=[DocumentProperties(prefix="SYS", title="System", parent="ROOT")],
    )

    main_frame.on_new_document(parent_prefix="ROOT")

    assert dialogs[0].init_kwargs["parent_prefix"] == "ROOT"
    assert dialogs[0].init_kwargs["parent_choices"][0][0] is None
    assert controller.created == [("SYS", "System", "ROOT")]
    main_frame._refresh_documents.assert_called_once_with(select="SYS", force_reload=True)
    assert main_frame._selected_requirement_id is None
    assert dialogs[0].destroyed


@pytest.mark.gui_smoke
def test_on_rename_document_updates_controller(main_frame, monkeypatch):
    """Renaming should update controller and always destroy the dialog."""

    doc = SimpleNamespace(prefix="REQ", title="Initial", parent="ROOT")

    class _Controller:
        def __init__(self):
            self.documents = {doc.prefix: doc}
            self.rename_calls = []

        def rename_document(self, prefix, *, title, parent=None):
            self.rename_calls.append((prefix, title, parent))

    controller = _Controller()
    main_frame.docs_controller = controller
    main_frame._refresh_documents = Mock()

    dialogs = _install_dialog_stub(
        monkeypatch,
        results=[wx.ID_OK],
        properties=[DocumentProperties(prefix="REQ", title="Renamed", parent=None)],
    )

    main_frame.on_rename_document("REQ")

    assert dialogs[0].init_kwargs["parent_prefix"] == "ROOT"
    assert all(value != "REQ" for value, _ in dialogs[0].init_kwargs["parent_choices"])
    assert controller.rename_calls == [("REQ", "Renamed", None)]
    main_frame._refresh_documents.assert_called_once_with(select="REQ", force_reload=True)
    assert dialogs[0].destroyed
