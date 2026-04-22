import pytest
import wx

from app.ui.editor_panel import EditorPanel

pytestmark = pytest.mark.gui


def test_links_render_as_two_column_table(wx_app):
    frame = wx.Frame(None)
    panel = EditorPanel(frame)
    panel.set_document(None)
    panel._show_link_picker = lambda _attr, selected_rids=None: ["SYS1", "SYS2"]  # type: ignore[method-assign]
    panel._on_add_link_generic("links")
    assert panel.links_panel.GetItemCount() == 2
    assert panel.links_panel.GetItem(0, 0).GetText() == "SYS1"
    assert panel.links_panel.GetItem(1, 0).GetText() == "SYS2"
    assert panel.links_panel.GetColumnCount() == 2
    assert panel.links_panel.HasFlag(wx.LC_NO_HEADER)
    frame.Destroy()
