import pytest
import wx

from app.ui.editor_panel import EditorPanel

pytestmark = pytest.mark.gui


def test_links_panel_refreshes_after_selection(wx_app, monkeypatch):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel._refresh_links_visibility("links")
    labels_before = [
        child.GetLabel()
        for child in panel.links_panel.GetChildren()
        if isinstance(child, wx.StaticText)
    ]
    assert "(none)" in labels_before

    called = {}

    def fake_fitinside():
        called["called"] = True

    monkeypatch.setattr(panel, "FitInside", fake_fitinside)
    panel._show_link_picker = lambda _attr, selected_rids=None: ["SYS1"]  # type: ignore[method-assign]
    panel._on_add_link_generic("links")

    labels_after = [
        child.GetLabel()
        for child in panel.links_panel.GetChildren()
        if isinstance(child, wx.StaticText)
    ]
    assert "SYS1" in labels_after
    assert called.get("called")
    frame.Destroy()
