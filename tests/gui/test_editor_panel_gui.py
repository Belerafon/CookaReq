"""Tests for editor panel gui."""

from dataclasses import asdict

import pytest

from app.core.labels import Label
from app.core.model import Priority, RequirementType, Status, Verification

pytestmark = pytest.mark.gui


def _make_panel():
    wx = pytest.importorskip("wx")
    frame = wx.Frame(None)
    from app.ui.editor_panel import EditorPanel

    return EditorPanel(frame)


def test_editor_new_requirement_resets(tmp_path, wx_app):
    panel = _make_panel()
    data = {
        "id": 1,
        "title": "T",
        "statement": "S",
        "attachments": [{"path": "a.txt", "note": "n"}],
        "labels": ["L1"],
        "revision": 5,
        "approved_at": "2025-01-01",
        "notes": "N",
    }
    panel.load(data, path=tmp_path / "req.json", mtime=123.0)
    panel.new_requirement()

    assert all(ctrl.GetValue() == "" for ctrl in panel.fields.values())
    panel.fields["id"].SetValue("1")
    defaults = panel.get_data()
    assert defaults.type == RequirementType.REQUIREMENT
    assert defaults.status == Status.DRAFT
    assert defaults.priority == Priority.MEDIUM
    assert defaults.verification == Verification.ANALYSIS
    assert panel.attachments == []
    assert panel.current_path is None
    assert panel.mtime is None
    assert defaults.labels == []
    assert defaults.revision == 1
    assert defaults.approved_at is None
    assert defaults.notes == ""


def test_editor_add_attachment_included(wx_app):
    panel = _make_panel()
    panel.new_requirement()
    panel.add_attachment("file.txt", "note")
    panel.fields["id"].SetValue("1")
    data = panel.get_data()
    assert [asdict(a) for a in data.attachments] == [
        {"path": "file.txt", "note": "note"},
    ]


def test_id_field_highlight_on_duplicate(tmp_path, wx_app):
    wx = pytest.importorskip("wx")
    from app.core import store

    existing = {
        "id": 1,
        "title": "T",
        "statement": "S",
        "type": "requirement",
        "status": "draft",
        "owner": "u",
        "priority": "medium",
        "source": "s",
        "verification": "analysis",
        "revision": 1,
    }
    store.save(tmp_path, existing)

    panel = _make_panel()
    panel.set_directory(tmp_path)
    panel.new_requirement()
    default = panel.fields["id"].GetBackgroundColour()

    panel.fields["id"].SetValue("1")
    wx.Yield()
    assert panel.fields["id"].GetBackgroundColour() != default

    panel.fields["id"].SetValue("2")
    wx.Yield()
    assert panel.fields["id"].GetBackgroundColour() == default


def test_editor_load_populates_fields(tmp_path, wx_app):
    panel = _make_panel()
    data = {
        "id": 1,
        "title": "Title",
        "statement": "Statement",
        "acceptance": "Accept",
        "owner": "Alice",
        "source": "Doc",
        "type": "constraint",
        "status": "in_review",
        "priority": "high",
        "verification": "test",
        "attachments": [{"path": "a.txt", "note": "n"}],
        "labels": ["L"],
        "revision": 2,
        "approved_at": "2025-01-02",
        "notes": "Note",
    }
    path = tmp_path / "req.json"
    panel.update_labels_list([Label("L", "#000000")])
    panel.load(data, path=path, mtime=42.0)

    result = panel.get_data()
    assert result.id == data["id"]
    assert result.title == data["title"]
    assert result.statement == data["statement"]
    assert result.acceptance == data["acceptance"]
    assert result.owner == data["owner"]
    assert result.source == data["source"]
    assert result.type.value == data["type"]
    assert result.status.value == data["status"]
    assert result.priority.value == data["priority"]
    assert result.verification.value == data["verification"]
    assert result.labels == data["labels"]
    assert [asdict(a) for a in result.attachments] == data["attachments"]
    assert result.revision == data["revision"]
    assert result.approved_at == data["approved_at"]
    assert result.notes == data["notes"]
    assert panel.current_path == path
    assert panel.mtime == 42.0


def test_editor_clone_resets_path_and_mtime(tmp_path, wx_app):
    panel = _make_panel()
    panel.load({"id": 1}, path=tmp_path / "old.json", mtime=1.0)
    panel.clone(2)
    assert panel.fields["id"].GetValue() == "2"
    assert panel.current_path is None
    assert panel.mtime is None


def test_editor_save_and_delete_roundtrip(tmp_path, wx_app):
    import json

    panel = _make_panel()
    panel.new_requirement()
    panel.fields["id"].SetValue("2")
    panel.fields["title"].SetValue("Title")
    saved_path = panel.save(tmp_path)

    assert saved_path.exists()
    assert panel.current_path == saved_path
    assert panel.mtime == saved_path.stat().st_mtime
    with saved_path.open() as fh:
        saved = json.load(fh)
    assert saved["id"] == 2
    assert saved["title"] == "Title"

    panel.delete()
    assert panel.current_path is None
    assert panel.mtime is None
    assert not saved_path.exists()


def test_editor_loads_links(tmp_path, wx_app):
    panel = _make_panel()
    data = {
        "id": 5,
        "parent": {"rid": "1", "revision": 1, "suspect": False},
        "links": {
            "verifies": [{"rid": "2", "revision": 1, "suspect": False}],
            "relates": [{"rid": "3", "revision": 1, "suspect": False}],
        },
    }
    panel.load(data, path=tmp_path / "req.json", mtime=0.0)
    result = panel.get_data()
    assert result.parent is not None and result.parent.rid == "1"
    assert result.links.verifies and result.links.verifies[0].rid == "2"
    assert result.links.relates and result.links.relates[0].rid == "3"


def test_multiline_fields_resize_dynamically(wx_app):
    panel = _make_panel()
    wx = pytest.importorskip("wx")
    panel.new_requirement()
    ctrl = panel.fields["statement"]
    wx.Yield()
    line_h = ctrl.GetCharHeight()
    start = ctrl.GetSize().height
    assert start >= line_h * 2
    ctrl.SetValue("one\ntwo\nthree")
    wx.Yield()
    grown = ctrl.GetSize().height
    assert grown >= line_h * 4
    assert grown > start
    ctrl.SetValue("single line")
    wx.Yield()
    shrunk = ctrl.GetSize().height
    assert shrunk < grown
    assert shrunk >= line_h * 2


def test_rationale_autosizes_without_affecting_statement(wx_app):
    panel = _make_panel()
    wx = pytest.importorskip("wx")
    panel.new_requirement()
    stmt = panel.fields["statement"]
    rat = panel.derivation_fields["rationale"]
    wx.Yield()
    line_h = rat.GetCharHeight()
    s_start = stmt.GetSize().height
    r_start = rat.GetSize().height
    assert s_start >= line_h * 2
    assert r_start >= line_h * 2
    rat.SetValue("one\ntwo\nthree")
    wx.Yield()
    s_after = stmt.GetSize().height
    r_after = rat.GetSize().height
    assert r_after >= line_h * 4
    assert r_after > r_start
    assert s_after == s_start
