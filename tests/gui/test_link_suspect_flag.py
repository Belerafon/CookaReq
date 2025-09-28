import pytest
import wx

import json
from pathlib import Path

from app.core.document_store import Document
from app.core.model import requirement_to_dict
from app.services.requirements import RequirementsService
from app.ui.editor_panel import EditorPanel

pytestmark = pytest.mark.gui


def _prepare_requirement(panel: EditorPanel) -> None:
    panel.new_requirement()
    panel.fields["id"].SetValue("1")
    panel.fields["title"].SetValue("Title")
    panel.fields["statement"].SetValue("Statement")
    panel.links_id.SetValue("SYS1")
    panel._on_add_link_generic("links")


def test_mark_link_as_suspect_updates_ui_and_serialization(wx_app):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_document(None)
    _prepare_requirement(panel)

    assert panel.links and panel.links[0]["suspect"] is False

    panel.set_link_suspect("links", 0, True)

    assert panel.links[0]["suspect"] is True
    assert panel.links_list.GetItemText(0, 1).startswith("⚠")
    assert panel.links_list.GetItemTextColour(0) != wx.NullColour

    req = panel.get_data()
    assert req.links[0].suspect is True
    data = requirement_to_dict(req)
    assert data["links"][0]["suspect"] is True
    frame.Destroy()


def test_clear_suspect_resets_display(wx_app):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_document(None)
    _prepare_requirement(panel)

    panel.set_link_suspect("links", 0, True)
    panel.set_link_suspect("links", 0, False)

    assert panel.links[0]["suspect"] is False
    assert not panel.links_list.GetItemText(0, 1).startswith("⚠")
    assert panel.links_list.GetItemTextColour(0) == wx.NullColour
    frame.Destroy()


def test_save_includes_suspect_flag(wx_app, tmp_path: Path):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    service = RequirementsService(tmp_path)
    service.save_document(Document(prefix="SYS", title="Test"))
    panel.set_service(service)
    panel.set_document("SYS")
    _prepare_requirement(panel)
    panel.set_link_suspect("links", 0, True)

    saved_path = panel.save("SYS")
    payload = json.loads(saved_path.read_text())
    assert payload["links"][0]["suspect"] is True
    frame.Destroy()
