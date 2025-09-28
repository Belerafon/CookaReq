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

    panel.links_id.SetValue("SYS123")
    panel._on_add_link_generic("links")

    assert panel.links_list.GetItemText(0, 0) == "SYS123"
    assert panel.links_list.GetItemText(0, 1) == "SYS123"
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

    assert panel.links_list.GetItemText(0, 0) == "SYS123"
    assert panel.links_list.GetItemText(0, 1) == "SYS123 — Parent (Systems)"
    frame.Destroy()
