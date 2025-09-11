"""Panel displaying requirements list and simple filters."""

import wx


class ListPanel(wx.Panel):
    """Panel with a search box and list of requirement titles."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.search = wx.SearchCtrl(self)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT)
        self.list.InsertColumn(0, "Title")
        sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)

    def set_requirements(self, requirements: list) -> None:
        """Populate list control with requirement titles."""
        self.list.DeleteAllItems()
        for req in requirements:
            title = req.get("title") if isinstance(req, dict) else getattr(req, "title", "")
            self.list.InsertItem(self.list.GetItemCount(), title)
