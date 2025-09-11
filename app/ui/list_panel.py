"""Panel displaying requirements list and simple filters."""

import wx


class ListPanel(wx.Panel):
    """Stub panel with search box and list control."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.search = wx.SearchCtrl(self)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT)
        sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)
