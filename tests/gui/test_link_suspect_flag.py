import pytest
import wx

from app.core.document_store import Document
from app.core.model import requirement_to_dict
from app.ui.editor_panel import EditorPanel

pytestmark = pytest.mark.gui


def _prepare_requirement(panel: EditorPanel) -> None:
    panel.new_requirement()
    panel.fields["id"].SetValue("1")
    panel.fields["title"].SetValue("Title")
    panel.fields["statement"].SetValue("Statement")
    panel.links_id.SetValue("SYS001")
    panel._on_add_link_generic("links")


def test_mark_link_as_suspect_updates_ui_and_serialization(wx_app):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
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
    _prepare_requirement(panel)

    panel.set_link_suspect("links", 0, True)
    panel.set_link_suspect("links", 0, False)

    assert panel.links[0]["suspect"] is False
    assert not panel.links_list.GetItemText(0, 1).startswith("⚠")
    assert panel.links_list.GetItemTextColour(0) == wx.NullColour
    frame.Destroy()


def test_save_includes_suspect_flag(wx_app, tmp_path, monkeypatch):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    _prepare_requirement(panel)
    panel.set_directory(tmp_path)
    panel.set_link_suspect("links", 0, True)

    monkeypatch.setattr("app.ui.editor_panel.list_item_ids", lambda directory, document: set())

    saved_payload: dict[str, dict] = {}

    def fake_save_item(directory, doc, data):
        saved_payload["data"] = data
        file_path = tmp_path / "requirement.json"
        file_path.write_text("{}")
        return file_path

    monkeypatch.setattr("app.ui.editor_panel.save_item", fake_save_item)

    doc = Document(prefix="SYS", title="Test", digits=3)
    panel.save(tmp_path, doc=doc)

    assert "data" in saved_payload
    assert saved_payload["data"]["links"][0]["suspect"] is True
    frame.Destroy()
