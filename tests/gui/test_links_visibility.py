import pytest
import wx

from app.ui.editor_panel import EditorPanel

pytestmark = pytest.mark.gui


def test_links_panel_refreshes_after_selection(wx_app, monkeypatch):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel._refresh_links_visibility("links")
    assert panel.links_panel.GetItemCount() == 0
    assert not panel.links_panel.IsShown()

    called = {}

    def fake_fitinside():
        called["called"] = True

    monkeypatch.setattr(panel, "FitInside", fake_fitinside)
    panel._show_link_picker = lambda _attr, selected_rids=None: ["SYS1"]  # type: ignore[method-assign]
    panel._on_add_link_generic("links")

    assert panel.links_panel.GetItemCount() == 1
    assert panel.links_panel.IsShown()
    assert panel.links_panel.GetItem(0, 0).GetText() == "SYS1"
    assert called.get("called")
    frame.Destroy()
