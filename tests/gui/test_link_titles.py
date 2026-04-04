import pytest
import wx

from app.core.document_store import Document
from app.services.requirements import RequirementsService
from app.ui.editor_panel import EditorPanel

pytestmark = pytest.mark.gui


def test_added_link_shows_id_and_title(wx_app):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_document(None)
    panel._show_link_picker = lambda _attr, selected_rids=None: ["SYS123"]  # type: ignore[method-assign]

    panel._on_add_link_generic("links")

    assert panel.links and panel.links[0]["rid"] == "SYS123"
    frame.Destroy()


def test_load_restores_link_metadata(wx_app, tmp_path):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    service = RequirementsService(tmp_path)
    service.save_document(Document(prefix="REQ", title="Requirements"))
    service.save_document(Document(prefix="SYS", title="Systems"))
    service.save_requirement_payload(
        "SYS",
        {
            "id": 123,
            "title": "Parent",
            "statement": "",
            "type": "requirement",
            "status": "draft",
            "owner": "",
            "priority": "medium",
            "source": "",
            "verification": "analysis",
            "acceptance": None,
            "assumptions": "",
            "conditions": "",
            "rationale": "",
            "labels": [],
            "attachments": [],
            "revision": 1,
            "modified_at": "",
            "notes": "",
        },
    )
    panel.set_service(service)
    panel.set_document("REQ")

    payload = {
        "id": 1,
        "title": "Child",
        "statement": "",
        "links": [{"rid": "SYS123"}],
    }

    panel.load(payload)

    assert panel.links and panel.links[0]["rid"] == "SYS123"
    assert panel.links[0]["title"] == "Parent"
    frame.Destroy()


def test_duplicate_link_is_not_added_twice(wx_app):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_document(None)
    panel._show_link_picker = lambda _attr, selected_rids=None: ["SYS123"]  # type: ignore[method-assign]
    panel._on_add_link_generic("links")
    panel._on_add_link_generic("links")

    assert len(panel.links) == 1
    frame.Destroy()


def test_pick_link_adds_selected_rid(wx_app, monkeypatch):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_document(None)
    monkeypatch.setattr(panel, "_show_link_picker", lambda _attr, selected_rids=None: ["SYS777"])
    panel._on_add_link_generic("links")

    assert len(panel.links) == 1
    assert panel.links[0]["rid"] == "SYS777"
    frame.Destroy()
