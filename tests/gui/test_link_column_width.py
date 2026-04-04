import pytest
import wx

from app.ui.editor_panel import EditorPanel

pytestmark = pytest.mark.gui


def test_links_render_as_comma_separated_labels(wx_app):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_document(None)
    panel._show_link_picker = lambda _attr, selected_rids=None: ["SYS1", "SYS2"]  # type: ignore[method-assign]
    panel._on_add_link_generic("links")
    labels = [
        child.GetLabel()
        for child in panel.links_panel.GetChildren()
        if isinstance(child, wx.StaticText)
    ]
    assert "SYS1" in labels
    assert ", " in labels
    assert "SYS2" in labels
    frame.Destroy()
