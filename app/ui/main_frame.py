"""Main application window."""

import re
import wx
from pathlib import Path
from dataclasses import fields
from typing import Dict

from app.core import store
from app.core.model import Requirement
from .list_panel import ListPanel
from .editor_panel import EditorPanel


class MainFrame(wx.Frame):
    """Top-level frame with basic menu and toolbar."""

    def __init__(self, parent: wx.Window | None):
        self._base_title = "CookaReq"
        self.config = wx.Config(appName="CookaReq")
        self.available_fields = [f.name for f in fields(Requirement) if f.name != "title"]
        self.selected_fields = self._load_columns()
        self.recent_dirs = self._load_recent_dirs()
        self._recent_items: Dict[int, Path] = {}
        super().__init__(parent=parent, title=self._base_title)
        self._create_menu()
        self._create_toolbar()
        self.splitter = wx.SplitterWindow(self)
        self.panel = ListPanel(
            self.splitter,
            on_clone=self.on_clone_requirement,
            on_delete=self.on_delete_requirement,
        )
        self.panel.set_columns(self.selected_fields)
        self.editor = EditorPanel(self.splitter, on_save=self._on_editor_save)
        self.splitter.SplitVertically(self.panel, self.editor, 300)
        self.editor.Hide()
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.splitter, 1, wx.EXPAND)
        self.SetSizer(sizer)
        self._load_layout()
        self.requirements: list[dict] = []
        self.current_dir: Path | None = None
        self.panel.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.on_requirement_selected)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    def _create_menu(self) -> None:
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        open_item = file_menu.Append(wx.ID_OPEN, "&Open Folder\tCtrl+O")
        self._recent_menu = wx.Menu()
        self._recent_menu_item = file_menu.AppendSubMenu(self._recent_menu, "Open &Recent")
        exit_item = file_menu.Append(wx.ID_EXIT, "E&xit")
        self.Bind(wx.EVT_MENU, self.on_open_folder, open_item)
        self.Bind(wx.EVT_MENU, lambda evt: self.Close(), exit_item)
        self._rebuild_recent_menu()
        menu_bar.Append(file_menu, "&File")

        view_menu = wx.Menu()
        self._column_items: Dict[int, str] = {}
        for field in self.available_fields:
            item = view_menu.AppendCheckItem(wx.ID_ANY, field)
            item.Check(field in self.selected_fields)
            self.Bind(wx.EVT_MENU, self.on_toggle_column, item)
            self._column_items[item.GetId()] = field
        menu_bar.Append(view_menu, "&View")
        self.SetMenuBar(menu_bar)

    def _create_toolbar(self) -> None:
        toolbar = self.CreateToolBar()
        open_tool = toolbar.AddTool(wx.ID_OPEN, "Open", wx.ArtProvider.GetBitmap(wx.ART_FOLDER_OPEN))
        new_tool = toolbar.AddTool(wx.ID_NEW, "New", wx.ArtProvider.GetBitmap(wx.ART_NEW))
        self.Bind(wx.EVT_TOOL, self.on_open_folder, open_tool)
        self.Bind(wx.EVT_TOOL, self.on_new_requirement, new_tool)
        toolbar.Realize()

    def on_open_folder(self, event: wx.Event) -> None:
        dlg = wx.DirDialog(self, "Select requirements folder")
        if dlg.ShowModal() == wx.ID_OK:
            self._load_directory(Path(dlg.GetPath()))
        dlg.Destroy()

    def on_open_recent(self, event: wx.CommandEvent) -> None:
        path = self._recent_items.get(event.GetId())
        if path:
            self._load_directory(path)

    def _load_directory(self, path: Path) -> None:
        """Load requirements from ``path`` and update recent list."""
        self._add_recent_dir(path)
        self.SetTitle(f"{self._base_title} - {path}")
        self.current_dir = path
        self.requirements = []
        for fp in self.current_dir.glob("*.json"):
            try:
                data, _ = store.load(fp)
                self.requirements.append(data)
            except Exception:
                continue
        self.panel.set_requirements(self.requirements)
        self.editor.Hide()

    # recent directories -------------------------------------------------
    def _load_recent_dirs(self) -> list[str]:
        value = self.config.Read("recent_dirs", "")
        return [p for p in value.split("|") if p]

    def _save_recent_dirs(self) -> None:
        self.config.Write("recent_dirs", "|".join(self.recent_dirs))
        self.config.Flush()

    def _add_recent_dir(self, path: Path) -> None:
        p = str(path)
        if p in self.recent_dirs:
            self.recent_dirs.remove(p)
        self.recent_dirs.insert(0, p)
        del self.recent_dirs[5:]
        self._save_recent_dirs()
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.Clear()
        self._recent_items.clear()
        for p in self.recent_dirs:
            item = self._recent_menu.Append(wx.ID_ANY, p)
            self.Bind(wx.EVT_MENU, self.on_open_recent, item)
            self._recent_items[item.GetId()] = Path(p)
        self._recent_menu_item.Enable(bool(self.recent_dirs))

    def on_requirement_selected(self, event: wx.ListEvent) -> None:
        idx = event.GetIndex()
        if 0 <= idx < len(self.requirements):
            self.editor.load(self.requirements[idx])
            self.editor.Show()
            self.splitter.UpdateSize()

    def _on_editor_save(self) -> None:
        if not self.current_dir:
            return
        path = self.editor.save(self.current_dir)
        data = self.editor.get_data()
        for i, req in enumerate(self.requirements):
            if req.get("id") == data.get("id"):
                self.requirements[i] = data
                break
        else:
            self.requirements.append(data)
        self.panel.set_requirements(self.requirements)

    def on_toggle_column(self, event: wx.CommandEvent) -> None:
        field = self._column_items.get(event.GetId())
        if not field:
            return
        if field in self.selected_fields:
            self.selected_fields.remove(field)
        else:
            self.selected_fields.append(field)
        self.panel.set_columns(self.selected_fields)
        self.panel.load_column_widths(self.config)
        self.panel.load_column_order(self.config)
        self._save_columns()

    def _load_columns(self) -> list[str]:
        value = self.config.Read("list_columns", "")
        return [f for f in value.split(",") if f]

    def _save_columns(self) -> None:
        self.config.Write("list_columns", ",".join(self.selected_fields))
        self.config.Flush()

    def _load_layout(self) -> None:
        """Restore window geometry, splitter, and column widths."""
        w = self.config.ReadInt("win_w", 800)
        h = self.config.ReadInt("win_h", 600)
        w = max(400, min(w, 3000))
        h = max(300, min(h, 2000))
        self.SetSize((w, h))
        x = self.config.ReadInt("win_x", -1)
        y = self.config.ReadInt("win_y", -1)
        if x != -1 and y != -1:
            self.SetPosition((x, y))
        else:
            self.Centre()
        sash = self.config.ReadInt("sash_pos", 300)
        client_w = self.GetClientSize().width
        sash = max(100, min(sash, max(client_w - 100, 100)))
        self.splitter.SetSashPosition(sash)
        self.panel.load_column_widths(self.config)
        self.panel.load_column_order(self.config)

    def _save_layout(self) -> None:
        """Persist window geometry, splitter, and column widths."""
        w, h = self.GetSize()
        x, y = self.GetPosition()
        self.config.WriteInt("win_w", w)
        self.config.WriteInt("win_h", h)
        self.config.WriteInt("win_x", x)
        self.config.WriteInt("win_y", y)
        self.config.WriteInt("sash_pos", self.splitter.GetSashPosition())
        self.panel.save_column_widths(self.config)
        self.panel.save_column_order(self.config)
        self.config.Flush()

    def _on_close(self, event: wx.Event) -> None:  # pragma: no cover - GUI event
        self._save_layout()
        event.Skip()

    # context menu actions -------------------------------------------
    def _generate_new_id(self, base: str | None = None) -> str:
        existing = {req["id"] for req in self.requirements}
        if base:
            match = re.match(r"^(.*?)(\d+)$", base)
            if match:
                prefix, num = match.groups()
                width = len(num)
                n = int(num)
                while True:
                    n += 1
                    candidate = f"{prefix}{n:0{width}d}"
                    if candidate not in existing:
                        return candidate
            base_candidate = f"{base}_copy"
            candidate = base_candidate
            counter = 1
            while candidate in existing:
                candidate = f"{base_candidate}{counter}"
                counter += 1
            return candidate
        prefix = "REQ-"
        n = 1
        candidate = f"{prefix}{n:03d}"
        while candidate in existing:
            n += 1
            candidate = f"{prefix}{n:03d}"
        return candidate

    def on_new_requirement(self, event: wx.Event) -> None:
        new_id = self._generate_new_id()
        self.editor.new_requirement()
        self.editor.fields["id"].SetValue(new_id)
        data = self.editor.get_data()
        self.requirements.append(data)
        self.panel.set_requirements(self.requirements)
        self.editor.Show()
        self.splitter.UpdateSize()

    def on_clone_requirement(self, index: int) -> None:
        if not (0 <= index < len(self.requirements)):
            return
        source = self.requirements[index]
        new_id = self._generate_new_id(source.get("id", ""))
        data = dict(source)
        data["id"] = new_id
        data["title"] = f"(Копия) {source.get('title', '')}".strip()
        data["modified_at"] = ""
        data["revision"] = 1
        self.requirements.append(data)
        self.panel.set_requirements(self.requirements)
        self.editor.load(data, path=None, mtime=None)
        self.editor.Show()
        self.splitter.UpdateSize()

    def on_delete_requirement(self, index: int) -> None:
        if not self.current_dir or not (0 <= index < len(self.requirements)):
            return
        req = self.requirements.pop(index)
        try:
            (self.current_dir / store.filename_for(req["id"])).unlink()
        except Exception:
            pass
        self.panel.set_requirements(self.requirements)
        self.editor.Hide()
        self.splitter.UpdateSize()
