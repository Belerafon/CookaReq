import os
import pytest
from app.i18n import _

from app.core.model import RequirementType, Status, Priority, Verification
from app.core.labels import Label


def _make_panel():
    wx = pytest.importorskip("wx")
    _app = wx.App()
    frame = wx.Frame(None)
    from app.ui.editor_panel import EditorPanel
    return EditorPanel(frame)


def _base_data():
    return {
        "id": 1,
        "title": "Title",
        "statement": "Statement",
        "type": "requirement",
        "status": "draft",
        "owner": "owner",
        "priority": "medium",
        "source": "src",
        "verification": "analysis",
        "revision": 1,
    }


def test_editor_save_and_delete(tmp_path):
    panel = _make_panel()
    panel.new_requirement()
    panel.fields["id"].SetValue("1")
    panel.fields["title"].SetValue("Title")
    panel.fields["statement"].SetValue("Statement")
    panel.fields["owner"].SetValue("owner")
    panel.fields["source"].SetValue("src")
    panel.fields["acceptance"].SetValue("Acc")
    panel.units_fields["quantity"].SetValue("kg")
    panel.units_fields["nominal"].SetValue("1.0")
    panel.units_fields["tolerance"].SetValue("0.1")
    wx = pytest.importorskip("wx")
    dt = wx.DateTime()
    dt.ParseISODate("2025-01-01")
    panel.approved_picker.SetValue(dt)
    panel.notes_ctrl.SetValue("Note")

    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir()
    att = attachments_dir / "file.txt"
    att.write_text("x")
    panel.add_attachment(str(att.relative_to(tmp_path)))

    path = panel.save(tmp_path)
    from app.core import store

    data, _ = store.load(path)
    assert data["id"] == 1
    assert data["attachments"][0]["path"] == f"attachments{os.sep}{att.name}"
    assert data["units"] == {"quantity": "kg", "nominal": 1.0, "tolerance": 0.1}
    assert data["approved_at"] == "2025-01-01"
    assert data["notes"] == "Note"

    panel.delete()
    assert not path.exists()


def test_editor_clone(tmp_path):
    from app.core import store

    orig_path = store.save(tmp_path, _base_data())
    orig_data, mtime = store.load(orig_path)

    panel = _make_panel()
    panel.load(orig_data, path=orig_path, mtime=mtime)
    panel.clone(2)
    new_path = panel.save(tmp_path)

    assert new_path != orig_path
    data, _ = store.load(new_path)
    assert data["id"] == 2
    assert data["title"] == orig_data["title"]


def test_get_data_requires_valid_id():
    panel = _make_panel()
    panel.new_requirement()
    with pytest.raises(ValueError):
        panel.get_data()
    panel.fields["id"].SetValue("abc")
    with pytest.raises(ValueError):
        panel.get_data()
    panel.fields["id"].SetValue("-5")
    with pytest.raises(ValueError):
        panel.get_data()
    panel.fields["id"].SetValue("10")
    data = panel.get_data()
    assert data.id == 10


def test_enum_localization_roundtrip():
    wx = pytest.importorskip("wx")
    from app.ui import locale

    panel = _make_panel()
    panel.new_requirement()
    panel.fields["id"].SetValue("1")
    data = panel.get_data()
    assert data.type == RequirementType.REQUIREMENT
    assert data.status == Status.DRAFT
    assert data.priority == Priority.MEDIUM
    assert data.verification == Verification.ANALYSIS

    panel.load(
        {
            "id": 1,
            "title": "T",
            "statement": "S",
            "type": "constraint",
            "status": "approved",
            "priority": "high",
            "verification": "test",
        }
    )
    assert panel.enums["type"].GetStringSelection() == locale.TYPE["constraint"]
    assert panel.enums["status"].GetStringSelection() == locale.STATUS["approved"]
    assert panel.enums["priority"].GetStringSelection() == locale.PRIORITY["high"]
    assert panel.enums["verification"].GetStringSelection() == locale.VERIFICATION["test"]

    panel.enums["type"].SetStringSelection(locale.TYPE["interface"])
    panel.enums["status"].SetStringSelection(locale.STATUS["baselined"])
    panel.enums["priority"].SetStringSelection(locale.PRIORITY["low"])
    panel.enums["verification"].SetStringSelection(locale.VERIFICATION["demonstration"])
    data = panel.get_data()
    assert data.type == RequirementType.INTERFACE
    assert data.status == Status.BASELINED
    assert data.priority == Priority.LOW
    assert data.verification == Verification.DEMONSTRATION


def test_labels_selection_and_update():
    panel = _make_panel()
    panel.update_labels_list([Label("ui", "#ff0000"), Label("backend", "#00ff00")])
    panel.new_requirement()
    panel.fields["id"].SetValue("1")
    panel.apply_label_selection(["backend"])
    data = panel.get_data()
    assert data.labels == ["backend"]
    panel.load({"id": 1, "labels": ["ui"]})
    assert panel.extra["labels"] == ["ui"]
    panel.update_labels_list([Label("docs", "#123456")])
    assert len(panel._label_defs) == 1
    assert panel.extra["labels"] == []


def test_loading_requirement_without_labels_clears_display():
    panel = _make_panel()
    panel.update_labels_list([Label("ui", "#ff0000")])
    panel.load({"id": 1, "labels": ["ui"]})
    assert panel.extra["labels"] == ["ui"]
    panel.load({"id": 2})
    assert panel.extra["labels"] == []
    children = panel.labels_panel.GetChildren()
    assert len(children) == 1
    assert children[0].GetLabel() == _("(none)")

