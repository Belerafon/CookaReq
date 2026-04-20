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
