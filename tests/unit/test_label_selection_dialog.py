import pytest
import wx
from pathlib import Path

from app.config import ConfigManager
from app.ui.editor_panel import EditorPanel
from app.ui.label_selection_dialog import LabelSelectionDialog
from app.core.document_store import LabelDef

pytestmark = pytest.mark.unit


def test_label_selection_dialog_freeform(wx_app):
    dlg = LabelSelectionDialog(
        None,
        [LabelDef(key="a", title="A", color="#111111")],
        [],
        allow_freeform=True,
    )
    dlg.list.CheckItem(0)
    assert dlg.freeform_ctrl is not None
    dlg.freeform_ctrl.SetValue("b, c , d")
    result = dlg.get_selected()
    assert result == ["a", "b", "c", "d"]
    dlg.Destroy()


def test_label_selection_dialog_inherited_toggle_is_persisted(
    wx_app: wx.App, tmp_path: Path
) -> None:
    config = ConfigManager(path=tmp_path / "config.json")
    parent = wx.Frame(None)
    parent.config = config  # type: ignore[attr-defined]
    try:
        dlg = LabelSelectionDialog(
            parent,
            [LabelDef(key="local", title="Local", color=None)],
            [],
            inherited_labels=[
                LabelDef(key="local", title="Local", color=None),
                LabelDef(key="parent", title="Parent", color=None),
            ],
        )
        assert dlg.inherited_toggle is not None
        assert dlg.list.GetItemCount() == 1
        dlg.inherited_toggle.SetValue(True)
        event = wx.CommandEvent(wx.EVT_CHECKBOX.typeId, dlg.inherited_toggle.GetId())
        event.SetInt(1)
        dlg._on_toggle_inherited(event)
        assert dlg.list.GetItemCount() == 2
        assert bool(config.get_value("labels_include_inherited")) is True
        dlg.Destroy()

        dlg2 = LabelSelectionDialog(
            parent,
            [LabelDef(key="local", title="Local", color=None)],
            [],
            inherited_labels=[
                LabelDef(key="local", title="Local", color=None),
                LabelDef(key="parent", title="Parent", color=None),
            ],
        )
        assert dlg2.inherited_toggle is not None
        assert dlg2.inherited_toggle.GetValue() is True
        assert dlg2.list.GetItemCount() == 2
        dlg2.Destroy()
    finally:
        parent.Destroy()


def test_label_selection_dialog_unchecked_label_is_removed_from_selection(wx_app: wx.App) -> None:
    dlg = LabelSelectionDialog(
        None,
        [
            LabelDef(key="backend", title="Backend", color=None),
            LabelDef(key="legacy", title="Legacy", color=None),
        ],
        ["backend", "legacy"],
    )
    try:
        assert dlg.list.IsItemChecked(0)
        assert dlg.list.IsItemChecked(1)
        dlg.list.CheckItem(1, False)
        result = dlg.get_selected()
        assert result == ["backend"]
    finally:
        dlg.Destroy()


def test_editor_panel_passes_full_inherited_labels_to_selection_dialog(
    wx_app: wx.App, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = wx.Frame(None)
    panel = EditorPanel(parent)

    class _ServiceStub:
        def collect_label_defs(
            self, prefix: str, *, include_inherited: bool = True
        ) -> tuple[list[LabelDef], bool]:
            assert prefix == "REQ"
            assert include_inherited is True
            return (
                [
                    LabelDef("local", "Local", None),
                    LabelDef("parent", "Parent", None),
                ],
                False,
            )

    captured: dict[str, list[str]] = {}

    class _DialogStub:
        def __init__(self, *_args, **kwargs):
            inherited = kwargs.get("inherited_labels") or []
            captured["keys"] = [lbl.key for lbl in inherited]

        def ShowModal(self):
            return wx.ID_CANCEL

        def Destroy(self):
            pass

    panel.set_service(_ServiceStub())  # type: ignore[arg-type]
    panel._doc_prefix = "REQ"
    panel.extra["doc_prefix"] = "REQ"
    panel.extra["labels"] = ["local"]
    panel._label_defs = [LabelDef("local", "Local", None)]
    monkeypatch.setattr("app.ui.editor_panel.LabelSelectionDialog", _DialogStub)
    panel._on_labels_click(wx.CommandEvent())

    assert captured["keys"] == ["local", "parent"]
    panel.Destroy()
    parent.Destroy()


def test_label_selection_dialog_shows_document_source_column(wx_app: wx.App) -> None:
    parent = wx.Frame(None)
    try:
        dlg = LabelSelectionDialog(
            parent,
            [LabelDef(key="local", title="Local", color=None)],
            [],
            inherited_labels=[
                LabelDef(key="local", title="Local", color=None),
                LabelDef(key="parent", title="Parent", color=None),
            ],
            label_sources={"local": "REQ"},
            inherited_label_sources={"local": "REQ", "parent": "SYS"},
        )
        assert dlg.list.GetColumnCount() == 3
        assert dlg.list.GetItemText(0, 2) == "REQ"
        if dlg.inherited_toggle is not None:
            dlg.inherited_toggle.SetValue(True)
            event = wx.CommandEvent(wx.EVT_CHECKBOX.typeId, dlg.inherited_toggle.GetId())
            event.SetInt(1)
            dlg._on_toggle_inherited(event)
        assert dlg.list.GetItemCount() == 2
        assert dlg.list.GetItemText(1, 2) == "SYS"
        dlg.Destroy()
    finally:
        parent.Destroy()


def test_label_selection_dialog_persists_layout_and_column_widths(
    wx_app: wx.App, tmp_path: Path
) -> None:
    config = ConfigManager(path=tmp_path / "config.json")
    parent = wx.Frame(None)
    parent.config = config  # type: ignore[attr-defined]
    labels = [
        LabelDef(key="local", title="Local", color=None),
        LabelDef(key="parent", title="Parent", color=None),
    ]
    try:
        dlg = LabelSelectionDialog(parent, labels, [], inherited_labels=labels)
        dlg.SetSize((780, 560))
        dlg.SetPosition((120, 140))
        dlg.list.SetColumnWidth(0, 180)
        dlg.list.SetColumnWidth(1, 220)
        dlg.list.SetColumnWidth(2, 260)
        dlg.Destroy()

        dlg_restored = LabelSelectionDialog(parent, labels, [], inherited_labels=labels)
        try:
            restored_size = dlg_restored.GetSize()
            restored_pos = dlg_restored.GetPosition()
            assert restored_size.GetWidth() == 780
            assert restored_size.GetHeight() == 560
            assert restored_pos.x == 120
            assert restored_pos.y == 140
            assert dlg_restored.list.GetColumnWidth(0) == 180
            assert dlg_restored.list.GetColumnWidth(1) == 220
            assert dlg_restored.list.GetColumnWidth(2) == 260
        finally:
            dlg_restored.Destroy()
    finally:
        parent.Destroy()
