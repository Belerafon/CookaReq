"""Main application window."""

import wx
from pathlib import Path
from app.core import store
from .list_panel import ListPanel
from .editor_panel import EditorPanel


class MainFrame(wx.Frame):
    """Top-level frame with basic menu and toolbar."""

    def __init__(self, parent: wx.Window | None):
        self._base_title = "CookaReq"
        super().__init__(parent=parent, title=self._base_title)
        self._create_menu()
        self._create_toolbar()
        self.splitter = wx.SplitterWindow(self)
        self.panel = ListPanel(self.splitter)
        self.editor = EditorPanel(self.splitter)
        self.splitter.SplitVertically(self.panel, self.editor, 300)
        self.editor.Hide()
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self.SetSize((800, 600))
        self.Centre()
        self.requirements: list[dict] = []
        self.panel.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_requirement_selected)

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
            self.requirements = []
            for fp in Path(path).glob("*.json"):
                try:
                    data, _ = store.load(fp)
                    self.requirements.append(data)
                except Exception:
                    continue
            self.panel.set_requirements(self.requirements)
            self.editor.Hide()
        dlg.Destroy()

    def on_requirement_selected(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self.requirements):
            self.editor.load(self.requirements[idx])
            self.editor.Show()
            self.splitter.UpdateSize()
