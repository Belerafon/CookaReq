"""Menu bar handling for the main frame."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import wx

from ..config import ConfigManager
from ..i18n import _
from . import locale


class Navigation:
    """Encapsulate menu bar construction."""

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
        on_toggle_hierarchy: Callable[[wx.CommandEvent], None],
        on_toggle_requirement_editor: Callable[[wx.CommandEvent], None],
        on_toggle_agent_chat: Callable[[wx.CommandEvent], None],
        on_show_derivation_graph: Callable[[wx.Event], None],
        on_show_trace_matrix: Callable[[wx.Event], None],
        on_new_requirement: Callable[[wx.Event], None],
        on_run_command: Callable[[wx.Event], None],
        on_open_logs: Callable[[wx.Event], None],
    ) -> None:
        """Initialize navigation menus and event handlers."""
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
        self.on_toggle_hierarchy = on_toggle_hierarchy
        self.on_toggle_requirement_editor = on_toggle_requirement_editor
        self.on_toggle_agent_chat = on_toggle_agent_chat
        self.on_show_derivation_graph = on_show_derivation_graph
        self.on_show_trace_matrix = on_show_trace_matrix
        self.on_new_requirement = on_new_requirement
        self.on_run_command = on_run_command
        self.on_open_logs = on_open_logs
        self._recent_items: dict[int, Path] = {}
        self._column_items: dict[int, str] = {}
        self.menu_bar = wx.MenuBar()
        self.log_menu_item: wx.MenuItem | None = None
        self.hierarchy_menu_item: wx.MenuItem | None = None
        self.editor_menu_item: wx.MenuItem | None = None
        self.agent_chat_menu_item: wx.MenuItem | None = None
        self.recent_menu = wx.Menu()
        self.recent_menu_item: wx.MenuItem | None = None
        self.run_command_id: int | None = None
        self._build()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        self._create_menu()

    def _create_menu(self) -> None:
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        open_item = file_menu.Append(wx.ID_OPEN, _("&Open Folder\tCtrl+O"))
        new_item = file_menu.Append(wx.ID_NEW, _("&New Requirement\tCtrl+N"))
        self.recent_menu = wx.Menu()
        self.recent_menu_item = file_menu.AppendSubMenu(
            self.recent_menu,
            _("Open &Recent"),
        )
        settings_item = file_menu.Append(wx.ID_PREFERENCES, _("Settings"))
        labels_item = file_menu.Append(wx.ID_ANY, _("Manage Labels"))
        exit_item = file_menu.Append(wx.ID_EXIT, _("E&xit"))
        self.frame.Bind(wx.EVT_MENU, self.on_open_folder, open_item)
        self.frame.Bind(wx.EVT_MENU, self.on_new_requirement, new_item)
        self.frame.Bind(wx.EVT_MENU, self.on_open_settings, settings_item)
        self.frame.Bind(wx.EVT_MENU, self.on_manage_labels, labels_item)
        self.frame.Bind(wx.EVT_MENU, lambda _evt: self.frame.Close(), exit_item)
        self._rebuild_recent_menu()
        self.manage_labels_id = labels_item.GetId()
        menu_bar.Append(file_menu, _("&File"))

        view_menu = wx.Menu()
        columns_menu = wx.Menu()
        self._column_items.clear()
        for field in self.available_fields:
            label = locale.field_label(field)
            item = columns_menu.AppendCheckItem(wx.ID_ANY, label)
            item.Check(field in self.selected_fields)
            self.frame.Bind(wx.EVT_MENU, self.on_toggle_column, item)
            self._column_items[item.GetId()] = field
        view_menu.AppendSubMenu(columns_menu, _("Columns"))
        self.hierarchy_menu_item = view_menu.AppendCheckItem(
            wx.ID_ANY,
            _("Show Hierarchy"),
        )
        self.frame.Bind(
            wx.EVT_MENU,
            self.on_toggle_hierarchy,
            self.hierarchy_menu_item,
        )
        self.editor_menu_item = view_menu.AppendCheckItem(
            wx.ID_ANY,
            _("Show Requirement Editor"),
        )
        self.frame.Bind(
            wx.EVT_MENU,
            self.on_toggle_requirement_editor,
            self.editor_menu_item,
        )
        self.log_menu_item = view_menu.AppendCheckItem(
            wx.ID_ANY,
            _("Show Log Console"),
        )
        self.frame.Bind(wx.EVT_MENU, self.on_toggle_log_console, self.log_menu_item)
        self.agent_chat_menu_item = view_menu.AppendCheckItem(
            wx.ID_ANY,
            _("Show Agent Chat"),
        )
        self.frame.Bind(wx.EVT_MENU, self.on_toggle_agent_chat, self.agent_chat_menu_item)
        graph_item = view_menu.Append(wx.ID_ANY, _("Show Derivation Graph"))
        self.frame.Bind(wx.EVT_MENU, self.on_show_derivation_graph, graph_item)
        trace_item = view_menu.Append(wx.ID_ANY, _("Show Trace Matrix"))
        self.frame.Bind(wx.EVT_MENU, self.on_show_trace_matrix, trace_item)
        menu_bar.Append(view_menu, _("&View"))

        tools_menu = wx.Menu()
        cmd_item = tools_menu.Append(wx.ID_ANY, _("Open Agent Chat\tCtrl+K"))
        self.frame.Bind(wx.EVT_MENU, self.on_run_command, cmd_item)
        self.run_command_id = cmd_item.GetId()
        logs_item = tools_menu.Append(wx.ID_ANY, _("Open Log Folder"))
        self.frame.Bind(wx.EVT_MENU, self.on_open_logs, logs_item)
        menu_bar.Append(tools_menu, _("&Tools"))
        self.menu_bar = menu_bar
        self.frame.SetMenuBar(self.menu_bar)

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
        """Rebuild menu, typically after language change."""
        self.selected_fields = selected_fields
        self.frame.SetMenuBar(None)
        self._build()

    def update_recent_menu(self) -> None:
        """Refresh menu showing recently opened directories."""

        self._rebuild_recent_menu()

    def get_field_for_id(self, item_id: int) -> str | None:
        """Return field name associated with menu ``item_id``."""

        return self._column_items.get(item_id)

    def get_recent_path(self, item_id: int) -> Path | None:
        """Return path associated with recent-menu ``item_id``."""

        return self._recent_items.get(item_id)
