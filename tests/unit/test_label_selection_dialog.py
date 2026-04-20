import pytest
import wx
from pathlib import Path

from app.config import ConfigManager
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
