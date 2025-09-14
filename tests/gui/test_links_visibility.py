import pytest
import wx

from app.ui.editor_panel import EditorPanel

pytestmark = pytest.mark.gui


def test_links_list_becomes_visible(wx_app, monkeypatch):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    assert not panel.derived_list.IsShown()

    called = {}

    def fake_fitinside():
        called['called'] = True

    monkeypatch.setattr(panel, "FitInside", fake_fitinside)
    panel.derived_id.SetValue('123')
    panel._on_add_link_generic('derived_from')

    assert panel.derived_list.IsShown()
    assert called.get('called')
    frame.Destroy()
