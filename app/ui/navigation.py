"""Menu bar and toolbar handling for the main frame."""

from __future__ import annotations

from gettext import gettext as _
from pathlib import Path
from typing import Callable, Dict

import wx

from app.config import ConfigManager


class Navigation:
    """Encapsulate menu bar and toolbar construction."""

    def __init__(
        self,
        frame: wx.Frame,
        config: ConfigManager,
        *,
        available_fields: list[str],
        selected_fields: list[str],
        on_open_folder: Callable[[wx.Event], None],
        on_open_settings: Callable[[wx.Event], None],
        on_manage_labels: Callable[[wx.Event], None],
        on_open_recent: Callable[[wx.CommandEvent], None],
        on_toggle_column: Callable[[wx.CommandEvent], None],
        on_toggle_log_console: Callable[[wx.CommandEvent], None],
        on_show_derivation_graph: Callable[[wx.Event], None],
        on_new_requirement: Callable[[wx.Event], None],
    ) -> None:
        self.frame = frame
        self.config = config
        self.available_fields = available_fields
        self.selected_fields = selected_fields
        self.on_open_folder = on_open_folder
        self.on_open_settings = on_open_settings
        self.on_manage_labels = on_manage_labels
        self.on_open_recent = on_open_recent
        self.on_toggle_column = on_toggle_column
        self.on_toggle_log_console = on_toggle_log_console
        self.on_show_derivation_graph = on_show_derivation_graph
        self.on_new_requirement = on_new_requirement
        self._recent_items: Dict[int, Path] = {}
        self._column_items: Dict[int, str] = {}
        self.menu_bar = wx.MenuBar()
        self.toolbar: wx.ToolBar | None = None
        self.log_menu_item: wx.MenuItem | None = None
        self.recent_menu = wx.Menu()
        self.recent_menu_item: wx.MenuItem | None = None
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        self._create_menu()
        self._create_toolbar()

    def _create_menu(self) -> None:
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        open_item = file_menu.Append(wx.ID_OPEN, _("&Open Folder\tCtrl+O"))
        self.recent_menu = wx.Menu()
        self.recent_menu_item = file_menu.AppendSubMenu(self.recent_menu, _("Open &Recent"))
        settings_item = file_menu.Append(wx.ID_PREFERENCES, _("Settings"))
        labels_item = file_menu.Append(wx.ID_ANY, _("Manage Labels"))
        exit_item = file_menu.Append(wx.ID_EXIT, _("E&xit"))
        self.frame.Bind(wx.EVT_MENU, self.on_open_folder, open_item)
        self.frame.Bind(wx.EVT_MENU, self.on_open_settings, settings_item)
        self.frame.Bind(wx.EVT_MENU, self.on_manage_labels, labels_item)
        self.frame.Bind(wx.EVT_MENU, lambda evt: self.frame.Close(), exit_item)
        self._rebuild_recent_menu()
        self.manage_labels_id = labels_item.GetId()
        menu_bar.Append(file_menu, _("&File"))

        view_menu = wx.Menu()
        columns_menu = wx.Menu()
        self._column_items.clear()
        for field in self.available_fields:
            item = columns_menu.AppendCheckItem(wx.ID_ANY, field)
            item.Check(field in self.selected_fields)
            self.frame.Bind(wx.EVT_MENU, self.on_toggle_column, item)
            self._column_items[item.GetId()] = field
        view_menu.AppendSubMenu(columns_menu, _("Columns"))
        self.log_menu_item = view_menu.AppendCheckItem(wx.ID_ANY, _("Show Error Console"))
        self.frame.Bind(wx.EVT_MENU, self.on_toggle_log_console, self.log_menu_item)
        graph_item = view_menu.Append(wx.ID_ANY, _("Show Derivation Graph"))
        self.frame.Bind(wx.EVT_MENU, self.on_show_derivation_graph, graph_item)
        menu_bar.Append(view_menu, _("&View"))
        self.menu_bar = menu_bar
        self.frame.SetMenuBar(self.menu_bar)

    def _create_toolbar(self) -> None:
        toolbar = self.frame.CreateToolBar()
        open_tool = toolbar.AddTool(wx.ID_OPEN, _("Open"), wx.ArtProvider.GetBitmap(wx.ART_FOLDER_OPEN))
        new_tool = toolbar.AddTool(wx.ID_NEW, _("New"), wx.ArtProvider.GetBitmap(wx.ART_NEW))
        self.frame.Bind(wx.EVT_TOOL, self.on_open_folder, open_tool)
        self.frame.Bind(wx.EVT_TOOL, self.on_new_requirement, new_tool)
        toolbar.Realize()
        self.toolbar = toolbar

    def _rebuild_recent_menu(self) -> None:
        for item in list(self.recent_menu.GetMenuItems()):
            self.recent_menu.Delete(item)
        self._recent_items.clear()
        for p in self.config.get_recent_dirs():
            item = self.recent_menu.Append(wx.ID_ANY, p)
            self.frame.Bind(wx.EVT_MENU, self.on_open_recent, item)
            self._recent_items[item.GetId()] = Path(p)
        if self.recent_menu_item:
            self.recent_menu_item.Enable(bool(self.config.get_recent_dirs()))

    # ------------------------------------------------------------------
    # public API
    def rebuild(self, selected_fields: list[str]) -> None:
        """Rebuild menu and toolbar, typically after language change."""
        self.selected_fields = selected_fields
        self.frame.SetMenuBar(None)
        if self.toolbar is not None:
            self.toolbar.Destroy()
        self._build()

    def update_recent_menu(self) -> None:
        self._rebuild_recent_menu()

    def get_field_for_id(self, item_id: int) -> str | None:
        return self._column_items.get(item_id)

    def get_recent_path(self, item_id: int) -> Path | None:
        return self._recent_items.get(item_id)
