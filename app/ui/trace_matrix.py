"""Simple frame displaying requirement trace links in a table."""

from __future__ import annotations

from collections.abc import Sequence

import wx

from ..i18n import _


class TraceMatrixFrame(wx.Frame):
    """Render a light-weight traceability matrix."""

    def __init__(self, parent: wx.Window | None, links: Sequence[tuple[str, str]]):
        super().__init__(parent=parent, title=_("Trace Matrix"))
        self.SetSize((400, 300))
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)
        list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.BORDER_SUNKEN)
        list_ctrl.InsertColumn(0, _("Child"))
        list_ctrl.InsertColumn(1, _("Parent"))
        for idx, (child, parent) in enumerate(links):
            list_ctrl.InsertItem(idx, child)
            list_ctrl.SetItem(idx, 1, parent)
        sizer.Add(list_ctrl, 1, wx.EXPAND | wx.ALL, 5)
        panel.SetSizer(sizer)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        main_sizer.Add(panel, 1, wx.EXPAND)
        self.SetSizer(main_sizer)
