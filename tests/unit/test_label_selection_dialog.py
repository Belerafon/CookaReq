import pytest
import wx

from app.ui.label_selection_dialog import LabelSelectionDialog
from app.core.labels import Label

pytestmark = pytest.mark.unit


def test_label_selection_dialog_freeform(wx_app):
    dlg = LabelSelectionDialog(None, [Label("a", "#111111")], [], allow_freeform=True)
    dlg.list.CheckItem(0)
    assert dlg.freeform_ctrl is not None
    dlg.freeform_ctrl.SetValue("b, c , d")
    result = dlg.get_selected()
    assert result == ["a", "b", "c", "d"]
    dlg.Destroy()
