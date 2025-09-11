import pytest


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

    attachments_dir = tmp_path / "attachments"
    attachments_dir.mkdir()
    att = attachments_dir / "file.txt"
    att.write_text("x")
    panel.add_attachment(str(att.relative_to(tmp_path)))

    path = panel.save(tmp_path)
    from app.core import store

    data, _ = store.load(path)
    assert data["id"] == 1
    assert data["attachments"][0]["path"] == f"attachments/{att.name}"

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


def test_enum_localization_roundtrip():
    wx = pytest.importorskip("wx")
    from app.ui import locale

    panel = _make_panel()
    panel.new_requirement()
    data = panel.get_data()
    assert data["type"] == "requirement"
    assert data["status"] == "draft"
    assert data["priority"] == "medium"
    assert data["verification"] == "analysis"

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
    assert data["type"] == "interface"
    assert data["status"] == "baselined"
    assert data["priority"] == "low"
    assert data["verification"] == "demonstration"

