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
    dlg.SetSize((420, 260))
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
