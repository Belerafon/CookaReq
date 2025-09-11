"""Main application window."""

import wx
from .list_panel import ListPanel


class MainFrame(wx.Frame):
    """Top-level frame with basic menu and toolbar."""

    def __init__(self, parent: wx.Window | None):
        self._base_title = "CookaReq"
        super().__init__(parent=parent, title=self._base_title)
        self._create_menu()
        self._create_toolbar()
        self.panel = ListPanel(self)
        self.SetSize((800, 600))
        self.Centre()

    def _create_menu(self) -> None:
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        open_item = file_menu.Append(wx.ID_OPEN, "&Open Folder\tCtrl+O")
        exit_item = file_menu.Append(wx.ID_EXIT, "E&xit")
        self.Bind(wx.EVT_MENU, self.on_open_folder, open_item)
        self.Bind(wx.EVT_MENU, lambda evt: self.Close(), exit_item)
        menu_bar.Append(file_menu, "&File")
        self.SetMenuBar(menu_bar)

    def _create_toolbar(self) -> None:
        toolbar = self.CreateToolBar()
        open_tool = toolbar.AddTool(wx.ID_OPEN, "Open", wx.ArtProvider.GetBitmap(wx.ART_FOLDER_OPEN))
        self.Bind(wx.EVT_TOOL, self.on_open_folder, open_tool)
        toolbar.Realize()

    def on_open_folder(self, event: wx.Event) -> None:
        dlg = wx.DirDialog(self, "Select requirements folder")
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self.SetTitle(f"{self._base_title} - {path}")
            # TODO: connect to storage later
            _ = path
        dlg.Destroy()
