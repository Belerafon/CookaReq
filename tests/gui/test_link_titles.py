import pytest
import wx
import types
from types import SimpleNamespace

from app.core.document_store import Document
from app.core.model import Verification
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
    assert panel.links_panel.GetItemCount() == 1
    assert panel.links_panel.GetItem(0, 0).GetText() == "SYS123"
    assert panel.links_panel.GetItem(0, 1).GetText() == "Parent"
    frame.Destroy()


def test_link_chip_has_statement_tooltip(wx_app, tmp_path):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    service = RequirementsService(tmp_path)
    service.save_document(Document(prefix="REQ", title="Requirements"))
    service.save_document(Document(prefix="SYS", title="Systems"))
    service.save_requirement_payload(
        "SYS",
        {
            "id": 123,
            "title": "Parent title for tooltip",
            "statement": "Parent full statement for tooltip",
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

    panel.load({"id": 1, "title": "Child", "statement": "", "links": [{"rid": "SYS123"}]})

    motion = types.SimpleNamespace(GetPosition=lambda: wx.Point(0, 0), Skip=lambda: None)
    panel.links_panel.HitTest = lambda _pos: (0, 0)  # type: ignore[method-assign]
    panel._on_links_list_motion("links", panel.links_panel, motion)  # type: ignore[arg-type]
    tooltip = panel.links_panel.GetToolTip()
    assert tooltip is not None
    assert tooltip.GetTip() == "Parent full statement for tooltip"
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


def test_remove_link_by_index_updates_links_table(wx_app):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_document(None)
    panel.links = [
        {"rid": "SYS1", "title": "First"},
        {"rid": "SYS2", "title": "Second"},
    ]
    panel._refresh_links_visibility("links")
    assert panel.links_panel.GetItemCount() == 2

    panel._remove_link_by_index("links", 0)

    assert [entry["rid"] for entry in panel.links] == ["SYS2"]
    assert panel.links_panel.GetItemCount() == 1
    assert panel.links_panel.GetItem(0, 0).GetText() == "SYS2"
    frame.Destroy()


def test_link_picker_uses_main_columns_and_shows_labels(wx_app, tmp_path):
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
            "status": "approved",
            "owner": "QA",
            "priority": "medium",
            "source": "Spec",
            "verification": "analysis",
            "acceptance": None,
            "assumptions": "",
            "conditions": "",
            "rationale": "",
            "labels": ["Safety", "UI"],
            "attachments": [],
            "revision": 1,
            "modified_at": "",
            "notes": "",
        },
    )
    panel.set_service(service)
    panel.set_document(None)
    panel.config = SimpleNamespace(get_columns=lambda: ["labels", "id", "source", "status"])  # type: ignore[attr-defined]

    candidates = panel._collect_link_picker_candidates("links")
    assert candidates and candidates[0]["labels"] == ["Safety", "UI"]
    columns = panel._resolve_link_picker_columns()
    assert columns == ["labels", "id", "source", "status"]
    frame.Destroy()


def test_link_picker_e2e_accepts_scalar_verification_and_opens_dialog(wx_app, tmp_path, monkeypatch):
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
            "statement": "Parent statement",
            "type": "requirement",
            "status": "approved",
            "owner": "QA",
            "priority": "medium",
            "source": "Spec",
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
    panel.set_document(None)

    candidates = panel._collect_link_picker_candidates("links")
    assert candidates and candidates[0]["verification"] == "analysis"

    panel._show_link_picker = EditorPanel._show_link_picker.__get__(panel, EditorPanel)  # type: ignore[method-assign]
    monkeypatch.setattr("app.ui.editor_panel.RequirementLinkPickerDialog.ShowModal", lambda self: wx.ID_CANCEL)

    picked = panel._show_link_picker("links", selected_rids={"SYS123"})

    assert picked == []
    loaded = service.load_requirements(prefixes=["SYS"])
    assert loaded and loaded[0].verification is Verification.ANALYSIS
    frame.Destroy()
