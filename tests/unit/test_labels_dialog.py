import wx
import pytest
from pathlib import Path

from app.config import ConfigManager
from app.core.document_store import LabelDef
from app.ui.labels_dialog import LabelsDialog

pytestmark = pytest.mark.unit


def test_labels_dialog_persists_geometry(wx_app: wx.App, tmp_path: Path) -> None:
    config = ConfigManager(path=tmp_path / "config.json")

    parent = wx.Frame(None)
    parent.config = config  # type: ignore[attr-defined]

    labels = [LabelDef(key="safety", title="Safety", color="#111111")]
    dlg = LabelsDialog(parent, labels)
    dlg.SetSize((620, 500))
    size_set = dlg.GetSize()
    dlg.SetPosition((30, 40))
    pos_set = dlg.GetPosition()
    dlg.Destroy()

    assert config.get_value("labels_w") == size_set.GetWidth()
    assert config.get_value("labels_h") == size_set.GetHeight()
    assert config.get_value("labels_x") == pos_set.x
    assert config.get_value("labels_y") == pos_set.y

    parent.Destroy()

    parent2 = wx.Frame(None)
    parent2.config = config  # type: ignore[attr-defined]

    dlg2 = LabelsDialog(parent2, labels)
    size = dlg2.GetSize()
    pos = dlg2.GetPosition()
    assert size.GetWidth() == size_set.GetWidth()
    assert size.GetHeight() == size_set.GetHeight()
    assert pos.x == pos_set.x
    assert pos.y == pos_set.y

    dlg2.Destroy()
    parent2.Destroy()


def test_labels_dialog_switches_document_and_resets_state(wx_app: wx.App) -> None:
    parent = wx.Frame(None)
    try:
        calls: list[str] = []

        def _loader(prefix: str) -> tuple[list[LabelDef], dict[str, int]]:
            calls.append(prefix)
            if prefix == "SYS":
                return [LabelDef(key="sys", title="System", color="#112233")], {"sys": 5}
            return [LabelDef(key="req", title="Req", color=None)], {"req": 1}

        dlg = LabelsDialog(
            parent,
            [LabelDef(key="req", title="Req", color=None)],
            usage_counts={"req": 1},
            document_choices=[("REQ", "REQ: Requirements"), ("SYS", "SYS: System")],
            current_document="REQ",
            on_document_change=_loader,
        )
        dlg._labels[0].title = "Updated"
        assert dlg._has_unsaved_changes()
        dlg._confirm_discard_unsaved_changes = lambda: True  # type: ignore[method-assign]
        assert dlg.document_choice is not None
        dlg.document_choice.SetSelection(1)
        event = wx.CommandEvent(wx.EVT_CHOICE.typeId, dlg.document_choice.GetId())
        event.SetInt(1)
        dlg._on_document_selected(event)
        assert calls == ["SYS"]
        assert dlg.get_selected_document() == "SYS"
        assert dlg.get_labels()[0].key == "sys"
        assert not dlg._has_unsaved_changes()
        dlg.Destroy()
    finally:
        parent.Destroy()


def test_labels_dialog_cancel_requires_discard_confirmation(wx_app: wx.App) -> None:
    parent = wx.Frame(None)
    try:
        dlg = LabelsDialog(parent, [LabelDef(key="req", title="Req", color=None)])
        dlg._labels[0].title = "Changed"
        assert dlg._has_unsaved_changes()
        modal_calls: list[int] = []
        dlg.EndModal = lambda code: modal_calls.append(code)  # type: ignore[method-assign]
        dlg._confirm_discard_unsaved_changes = lambda: False  # type: ignore[method-assign]
        dlg._on_cancel(wx.CommandEvent(wx.EVT_BUTTON.typeId, wx.ID_CANCEL))
        assert modal_calls == []
        dlg._confirm_discard_unsaved_changes = lambda: True  # type: ignore[method-assign]
        dlg._on_cancel(wx.CommandEvent(wx.EVT_BUTTON.typeId, wx.ID_CANCEL))
        assert modal_calls == [wx.ID_CANCEL]
        dlg.Destroy()
    finally:
        parent.Destroy()


def test_labels_dialog_uses_larger_default_size_and_help_text(wx_app: wx.App) -> None:
    parent = wx.Frame(None)
    try:
        dlg = LabelsDialog(parent, [LabelDef(key="req", title="Req", color=None)])
        size = dlg.GetSize()
        assert size.GetWidth() >= dlg.FromDIP(580)
        assert size.GetHeight() >= dlg.FromDIP(420)
        assert "label" in dlg._help_text.casefold()  # type: ignore[attr-defined]
        dlg.Destroy()
    finally:
        parent.Destroy()


def test_labels_dialog_discard_confirmation_uses_confirm_signature(
    wx_app: wx.App, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = wx.Frame(None)
    try:
        dlg = LabelsDialog(parent, [LabelDef(key="req", title="Req", color=None)])
        dlg._labels[0].title = "Changed"
        captured: list[str] = []
        monkeypatch.setattr(
            "app.ui.labels_dialog.confirm",
            lambda message: captured.append(message) or True,
        )
        assert dlg._confirm_discard_unsaved_changes()
        assert captured == ["Discard unsaved label changes?"]
        dlg.Destroy()
    finally:
        parent.Destroy()


def test_labels_dialog_marks_unsaved_state_in_title(wx_app: wx.App) -> None:
    parent = wx.Frame(None)
    try:
        dlg = LabelsDialog(parent, [LabelDef(key="req", title="Req", color=None)])
        assert "*" not in dlg.GetTitle()
        dlg._labels[0].title = "Changed"
        dlg._update_dirty_state()
        assert "*" in dlg.GetTitle()
        dlg._replace_state([LabelDef(key="req", title="Req", color=None)], {"req": 1})
        assert "*" not in dlg.GetTitle()
        dlg.Destroy()
    finally:
        parent.Destroy()


def test_labels_dialog_double_click_activates_edit(wx_app: wx.App) -> None:
    parent = wx.Frame(None)
    try:
        dlg = LabelsDialog(parent, [LabelDef(key="req", title="Req", color=None)])
        calls: list[str] = []
        dlg._on_edit_selected = lambda _event: calls.append("edit")  # type: ignore[method-assign]
        dlg._on_activate_item(wx.ListEvent())
        assert calls == ["edit"]
        dlg.Destroy()
    finally:
        parent.Destroy()
