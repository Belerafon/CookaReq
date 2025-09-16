"""Tests for cloning and deriving requirements from the main frame."""

import importlib

import pytest

from app.core.document_store import Document, save_document, save_item
from app.core.model import (
    Priority,
    Requirement,
    RequirementType,
    Status,
    Verification,
    requirement_to_dict,
)
from app.ui.controllers import DocumentsController
from app.ui.requirement_model import RequirementModel

pytestmark = pytest.mark.gui


def _req(req_id: int, title: str) -> Requirement:
    return Requirement(
        id=req_id,
        title=title,
        statement="",
        type=RequirementType.REQUIREMENT,
        status=Status.DRAFT,
        owner="",
        priority=Priority.MEDIUM,
        source="",
        verification=Verification.ANALYSIS,
    )


def _prepare_frame(monkeypatch, tmp_path):
    wx = pytest.importorskip("wx")
    import app.ui.main_frame as main_frame_mod

    importlib.reload(main_frame_mod)
    monkeypatch.setattr(main_frame_mod.MCPController, "start", lambda self, settings: None)

    model = RequirementModel()
    frame = main_frame_mod.MainFrame(None, model=model)
    doc = Document(prefix="REQ", title="Doc", digits=3)
    doc_dir = tmp_path / "REQ"
    save_document(doc_dir, doc)
    base_req = _req(1, "Base")
    save_item(doc_dir, doc, requirement_to_dict(base_req))

    controller = DocumentsController(tmp_path, model)
    controller.load_documents()
    controller.load_items("REQ")

    frame.docs_controller = controller
    frame.current_dir = tmp_path
    frame.current_doc_prefix = "REQ"
    frame.panel.set_documents_controller(controller)
    frame.panel.set_active_document("REQ")
    frame.panel.recalc_derived_map(model.get_all())
    frame.editor.set_directory(doc_dir)
    return frame


def test_clone_creates_new_requirement(monkeypatch, wx_app, tmp_path):
    frame = _prepare_frame(monkeypatch, tmp_path)
    wx = pytest.importorskip("wx")

    try:
        wx_app.Yield()
        frame.on_clone_requirement(1)
        wx_app.Yield()

        assert frame._selected_requirement_id == 2
        assert frame.editor.fields["id"].GetValue() == "2"
        assert frame.editor.IsShown()

        clone = frame.model.get_by_id(2)
        assert clone is not None
        assert clone.title.startswith("(Copy)")

        selected = frame.panel.list.GetFirstSelected()
        assert selected != wx.NOT_FOUND
        assert frame.panel.list.GetItemData(selected) == 2
    finally:
        frame.Destroy()


def test_derive_creates_linked_requirement(monkeypatch, wx_app, tmp_path):
    frame = _prepare_frame(monkeypatch, tmp_path)
    wx = pytest.importorskip("wx")

    try:
        wx_app.Yield()
        source = frame.model.get_by_id(1)
        assert source is not None
        parent_rid = source.rid or "REQ-001"

        frame.on_derive_requirement(1)
        wx_app.Yield()

        assert frame._selected_requirement_id == 2
        derived = frame.model.get_by_id(2)
        assert derived is not None
        assert derived.title.startswith("(Derived)")
        assert any(
            getattr(link, "rid", str(link)) == parent_rid for link in derived.links
        )

        mapping = frame.panel.derived_map[parent_rid]
        assert 2 in mapping

        selected = frame.panel.list.GetFirstSelected()
        assert selected != wx.NOT_FOUND
        assert frame.panel.list.GetItemData(selected) == 2
    finally:
        frame.Destroy()

