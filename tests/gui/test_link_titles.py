import pytest
import wx

from app.core.document_store import Document
from app.ui.editor_panel import EditorPanel

pytestmark = pytest.mark.gui


def test_added_link_shows_id_and_title(wx_app, monkeypatch):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_directory("dummy")

    panel.links_id.SetValue("SYS123")
    panel._on_add_link_generic("links")

    assert panel.links_list.GetItemText(0, 0) == "SYS123"
    assert panel.links_list.GetItemText(0, 1) == "SYS123"
    frame.Destroy()


def test_load_restores_link_metadata(wx_app, tmp_path, monkeypatch):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_directory(tmp_path / "REQ")

    doc = Document(prefix="SYS", title="Systems")

    def fake_load_document(path):
        assert path == tmp_path / "SYS"
        return doc

    def fake_load_item(path, loaded_doc, item_id):
        assert path == tmp_path / "SYS"
        assert loaded_doc is doc
        assert item_id == 123
        return ({"title": "Parent", "statement": ""}, 0.0)

    monkeypatch.setattr("app.ui.editor_panel.load_document", fake_load_document)
    monkeypatch.setattr("app.ui.editor_panel.load_item", fake_load_item)

    payload = {
        "id": 1,
        "title": "Child",
        "statement": "",
        "links": [{"rid": "SYS123"}],
    }

    panel.load(payload)

    assert panel.links_list.GetItemText(0, 0) == "SYS123"
    assert panel.links_list.GetItemText(0, 1) == "SYS123 — Parent (Systems)"
    frame.Destroy()
