"""Panel displaying requirements list and simple filters."""

import wx

from typing import List


class ListPanel(wx.Panel):
    """Panel with a search box and list of requirement fields."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.search = wx.SearchCtrl(self)
        self.list = wx.ListCtrl(self, style=wx.LC_REPORT)
        self.columns: List[str] = []
        self._requirements: List = []
        self._setup_columns()
        sizer.Add(self.search, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)
        self.SetSizer(sizer)

    def _setup_columns(self) -> None:
        """Configure list control columns based on selected fields."""
        self.list.ClearAll()
        self.list.InsertColumn(0, "Title")
        for idx, field in enumerate(self.columns, start=1):
            self.list.InsertColumn(idx, field)

    def set_columns(self, fields: List[str]) -> None:
        """Set additional columns (beyond Title) to display."""
        self.columns = fields
        self._setup_columns()
        # repopulate with existing requirements after changing columns
        self.set_requirements(self._requirements)

    def set_requirements(self, requirements: list) -> None:
        """Populate list control with requirement data."""
        self._requirements = requirements
        self.list.DeleteAllItems()
        for req in requirements:
            title = req.get("title") if isinstance(req, dict) else getattr(req, "title", "")
            index = self.list.InsertItem(self.list.GetItemCount(), title)
            for col, field in enumerate(self.columns, start=1):
                if isinstance(req, dict):
                    value = req.get(field, "")
                else:
                    value = getattr(req, field, "")
                self.list.SetItem(index, col, str(value))
