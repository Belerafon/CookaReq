"""Tests for MainFrame dirty-state confirmation logic."""

import pytest


pytestmark = pytest.mark.gui


def test_confirm_discard_changes(monkeypatch, wx_app):
    pytest.importorskip("wx")

    import app.ui.main_frame as main_frame_mod

    frame = main_frame_mod.MainFrame(None)
    try:
        frame.editor.fields["title"].ChangeValue("Dirty")
        assert frame.editor.is_dirty() is True

        messages: list[str] = []

        def reject(message: str) -> bool:
            messages.append(message)
            return False

        monkeypatch.setattr(main_frame_mod, "confirm", reject)

        assert frame._confirm_discard_changes() is False
        assert messages[-1] == main_frame_mod._("Discard unsaved changes?")
        assert frame.editor.is_dirty() is True

        def accept(message: str) -> bool:
            messages.append(message)
            return True

        monkeypatch.setattr(main_frame_mod, "confirm", accept)

        assert frame._confirm_discard_changes() is True
        assert messages[-1] == main_frame_mod._("Discard unsaved changes?")
        assert frame.editor.is_dirty() is False
    finally:
        frame.Destroy()


def test_document_selection_rejected_when_dirty(monkeypatch, wx_app, tmp_path):
    pytest.importorskip("wx")

    import wx

    import app.ui.main_frame as main_frame_mod
    from app.core.doc_store import Document

    frame = main_frame_mod.MainFrame(None)
    try:
        doc_a = Document(prefix="DOC", title="Doc", digits=3)
        doc_b = Document(prefix="FEA", title="Feature", digits=3)
        docs = {"DOC": doc_a, "FEA": doc_b}
        frame.doc_tree.set_documents(docs)

        class DummyController:
            def __init__(self) -> None:
                self.documents = docs
                self.load_calls: list[str] = []
                self.collect_calls: list[str] = []

            def load_items(self, prefix: str) -> dict:
                self.load_calls.append(prefix)
                return {}

            def collect_labels(self, prefix: str) -> tuple[list, bool]:
                self.collect_calls.append(prefix)
                return ([], False)

        controller = DummyController()
        frame.docs_controller = controller
        frame.current_dir = tmp_path

        initial_item = frame.doc_tree._node_for_prefix["DOC"]
        frame.doc_tree.tree.SelectItem(initial_item)
        wx.YieldIfNeeded()

        assert controller.load_calls == ["DOC"]
        assert controller.collect_calls == ["DOC"]
        assert frame.current_doc_prefix == "DOC"

        frame.editor.fields["title"].ChangeValue("Dirty")
        assert frame.editor.is_dirty() is True

        messages: list[str] = []

        def reject(message: str) -> bool:
            messages.append(message)
            return False

        monkeypatch.setattr(main_frame_mod, "confirm", reject)

        frame.doc_tree.tree.SelectItem(frame.doc_tree._node_for_prefix["FEA"])
        wx.YieldIfNeeded()

        assert controller.load_calls == ["DOC"]
        assert controller.collect_calls == ["DOC"]
        assert frame.current_doc_prefix == "DOC"
        assert frame.doc_tree.tree.GetSelection() == initial_item
        assert messages[-1] == main_frame_mod._("Discard unsaved changes?")
        assert frame.editor.is_dirty() is True
    finally:
        frame.Destroy()


def test_requirement_selection_rejected_when_dirty(monkeypatch, wx_app, tmp_path):
    pytest.importorskip("wx")

    import wx

    import app.ui.main_frame as main_frame_mod
    from app.core.doc_store import Document
    from app.core.model import (
        Requirement,
        RequirementType,
        Status,
        Priority,
        Verification,
    )

    frame = main_frame_mod.MainFrame(None)
    try:
        doc = Document(prefix="DOC", title="Doc", digits=3)
        docs = {"DOC": doc}
        frame.doc_tree.set_documents(docs)

        class DummyController:
            def __init__(self) -> None:
                self.documents = docs

            def load_items(self, prefix: str) -> dict:
                return {}

            def collect_labels(self, prefix: str) -> tuple[list, bool]:
                return ([], False)

        frame.docs_controller = DummyController()
        frame.current_dir = tmp_path

        req1 = Requirement(
            id=1,
            title="Req 1",
            statement="Statement 1",
            type=RequirementType.REQUIREMENT,
            status=Status.DRAFT,
            owner="Owner",
            priority=Priority.MEDIUM,
            source="Source",
            verification=Verification.ANALYSIS,
        )
        req2 = Requirement(
            id=2,
            title="Req 2",
            statement="Statement 2",
            type=RequirementType.REQUIREMENT,
            status=Status.DRAFT,
            owner="Owner",
            priority=Priority.MEDIUM,
            source="Source",
            verification=Verification.ANALYSIS,
        )
        frame.model.set_requirements([req1, req2])

        doc_item = frame.doc_tree._node_for_prefix["DOC"]
        frame.doc_tree.tree.SelectItem(doc_item)
        wx.YieldIfNeeded()

        frame.panel.list.Select(0)
        wx.YieldIfNeeded()

        assert frame._selected_requirement_id == 1

        frame.editor.fields["title"].ChangeValue("Dirty")
        assert frame.editor.is_dirty() is True

        messages: list[str] = []

        def reject(message: str) -> bool:
            messages.append(message)
            return False

        monkeypatch.setattr(main_frame_mod, "confirm", reject)

        frame.panel.list.Select(1)
        wx.YieldIfNeeded()

        assert messages[-1] == main_frame_mod._("Discard unsaved changes?")
        assert frame._selected_requirement_id == 1
        assert frame.panel.list.GetFirstSelected() == 0
        assert frame.editor.fields["title"].GetValue() == "Dirty"
    finally:
        frame.Destroy()
